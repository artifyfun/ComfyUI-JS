import atexit
import json
import re
import shutil
import subprocess
import threading
from collections import deque

import execjs

default_code = r"""
  // input1 ~ input6 any
  // return any
  try {
    if (input1 > input2) {
      return input3.toUpperCase();
    } else {
      return input4.toUpperCase();
    }
  } catch (e) {
    return input5
  }
"""

multi_code = r"""
  // input1 ~ input6 any
  // return any[]
  return [input1 * 2, input2 + '_subfix', Number(input3), input4, input5, input6]
"""

class AlwaysEqualProxy(str):
    def __eq__(self, _):
        return True

    def __ne__(self, _):
        return False

any_type = AlwaysEqualProxy("*")

# ---------------------------------------------------------------------------
# 常驻 Node 引擎：一次启动、反复复用，替代 PyExecJS 每次起新进程
# ---------------------------------------------------------------------------

# Node worker：通过 stdin 读取 JSON 行请求，stdout 返回 JSON 行响应。
# 使用 vm.Script 缓存编译结果；vm.runInContext 带 timeout，死循环会被强制中断。
_NODE_WORKER = r"""
const readline = require('readline');
const vm = require('vm');

const rl = readline.createInterface({ input: process.stdin, terminal: false });
const CACHE = new Map();
const CACHE_MAX = 64;
const TIMEOUT_MS = 10000;

function buildScript(code) {
  return new vm.Script(
    '(function() { const _f = (function(input1, input2, input3, input4, input5, input6) {\n' +
    code + '\n}); return _f.apply(null, __args__); })()',
    { filename: 'user_code.js' }
  );
}

function getScript(code) {
  let s = CACHE.get(code);
  if (!s) {
    s = buildScript(code);
    CACHE.set(code, s);
    if (CACHE.size > CACHE_MAX) CACHE.delete(CACHE.keys().next().value);
  }
  return s;
}

function serialize(v) {
  if (v === undefined) return null;
  try {
    return JSON.parse(JSON.stringify(v, function (k, val) {
      if (typeof val === 'bigint') return val.toString();
      if (typeof val === 'number' && !Number.isFinite(val)) return null;
      if (typeof val === 'function' || typeof val === 'symbol') return String(val);
      return val;
    }));
  } catch (e) {
    return String(v);
  }
}

// 用户代码里的 console 输出走 stderr，避免污染 stdout 的 JSON 协议
const userConsole = {
  log:   (...a) => process.stderr.write(a.map(String).join(' ') + '\n'),
  info:  (...a) => process.stderr.write(a.map(String).join(' ') + '\n'),
  warn:  (...a) => process.stderr.write(a.map(String).join(' ') + '\n'),
  error: (...a) => process.stderr.write(a.map(String).join(' ') + '\n'),
};

rl.on('line', (line) => {
  let req;
  try {
    req = JSON.parse(line);
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: 'bad request: ' + e.message }) + '\n');
    return;
  }
  try {
    const sandbox = { __args__: req.args || [], require, console: userConsole, Buffer };
    vm.createContext(sandbox);
    const result = getScript(req.code).runInContext(sandbox, { timeout: TIMEOUT_MS });
    process.stdout.write(JSON.stringify({ ok: true, result: serialize(result) }) + '\n');
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: String((e && e.stack) || e) }) + '\n');
  }
});

rl.on('close', () => process.exit(0));
"""


class NodeJsEngine:
    """常驻 Node 子进程，JSON 行协议通信。线程安全，进程崩溃自动重启。"""

    def __init__(self, node_bin):
        self._node = node_bin
        self._proc = None
        self._lock = threading.Lock()
        self._stderr = deque(maxlen=200)
        self._stderr_thread = None
        atexit.register(self.shutdown)

    def _start(self):
        self._proc = subprocess.Popen(
            [self._node, '-e', _NODE_WORKER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            bufsize=1,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self):
        try:
            for line in self._proc.stderr:
                self._stderr.append(line.rstrip())
        except Exception:
            pass

    def _ensure(self):
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        return self._proc

    def call(self, code, args):
        with self._lock:
            proc = self._ensure()
            try:
                req = json.dumps({"code": code, "args": args}, ensure_ascii=False)
                proc.stdin.write(req + "\n")
                proc.stdin.flush()
                resp = proc.stdout.readline()
                if not resp:
                    raise RuntimeError("Node 引擎异常退出: " + " | ".join(list(self._stderr)[-8:]))
                out = json.loads(resp)
                if not out.get("ok"):
                    raise RuntimeError(out.get("error") or "unknown JS error")
                return out.get("result")
            except (BrokenPipeError, OSError, ValueError):
                # 进程已死/输出损坏：关闭后抛错，下次调用会自动重启
                self.shutdown()
                raise

    def shutdown(self):
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                self._proc = None


_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def _get_engine():
    """获取全局常驻引擎；找不到 node 时返回 None（调用方回退 PyExecJS）。"""
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                node = shutil.which("node")
                _ENGINE = NodeJsEngine(node) if node else None
    return _ENGINE


# ---------------------------------------------------------------------------
# 输入安全化 + 统一错误翻译
# ---------------------------------------------------------------------------

def _json_safe(value):
    """把任意 ComfyUI 输入转成可被 json 序列化的值，避免崩溃。

    IMAGE/MASK tensor、自定义对象等会被降级为 tolist()/item()/str()。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        pass
    # numpy / torch tensor 等
    for method in ("tolist", "item"):
        f = getattr(value, method, None)
        if callable(f):
            try:
                return _json_safe(f())
            except Exception:
                pass
    try:
        return str(value)
    except Exception:
        return None


def _get_runtime():
    """PyExecJS 回退路径：优先 Node，不可用回退默认运行时。"""
    try:
        return execjs.get("Node")
    except Exception:
        return execjs.get()


def _extract_js_error(e):
    """把异常信息翻译成可读文本，尽量保留出错行号。

    兼容两种来源：
    - 常驻引擎返回的 node stack（含 user_code.js:N）
    - PyExecJS 回退路径的 stderr（含 [stdin]:N）
    """
    raw = str(e)

    # 提取出错行号（常驻引擎 user_code.js:N 是包裹脚本行号，用户代码从第 2 行开始，故减 1）
    line_no = ""
    m = re.search(r"user_code\.js:(\d+)", raw)
    if m:
        line_no = f"[第 {max(1, int(m.group(1)) - 1)} 行] "
    else:
        m = re.search(r"\[stdin\]:(\d+)", raw)
        if m:
            line_no = f"[第 {m.group(1)} 行] "

    # 提取错误描述（SyntaxError / ReferenceError / ... 及常见语法错误短语）
    err_desc = ""
    m = re.search(
        r"\b(?:SyntaxError|ReferenceError|TypeError|RangeError|URIError|EvalError|Error|Uncaught)[^:\n]*:\s*[^\n]+",
        raw,
    )
    if m:
        err_desc = m.group(0).strip()
    else:
        m = re.search(
            r"(?:Unexpected token|Expression expected|Invalid or unexpected token|Unterminated[^\n]*|"
            r"Script execution timed out[^\n]*)",
            raw,
        )
        if m:
            err_desc = m.group(0).strip()

    if err_desc:
        return line_no + err_desc
    return (line_no + raw)[:400]


def _check_markdown(code):
    """检测代码中疑似混入的 markdown 语法（行首标记），返回提示列表。

    注意：模板字符串(反引号)内放 markdown 是合法用法，正常执行时不会走到
    这里的提示；只有执行失败(如反引号嵌套破坏语法)时才会用于辅助诊断。
    """
    hints = []
    for i, line in enumerate(code.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        if re.match(r"^#{1,6}\s", s):
            hints.append(f"第{i}行疑似 markdown 标题 '# ...'")
        elif re.match(r"^\*\*.*\*\*$", s):
            hints.append(f"第{i}行疑似 markdown 加粗 '**...**'")
        elif re.match(r"^[-*+]\s+\S", s):
            hints.append(f"第{i}行疑似 markdown 列表 '- ...'")
        elif re.match(r"^>\s", s):
            hints.append(f"第{i}行疑似 markdown 引用 '> ...'")
        elif s.startswith("```"):
            hints.append(f"第{i}行疑似 markdown 代码块围栏 '```'")
        elif re.match(r"^\|.*\|$", s):
            hints.append(f"第{i}行疑似 markdown 表格 '| ... |'")
    return hints[:3]


def _markdown_advice(code):
    """针对「模板字符串内嵌 markdown」给出可执行的修复建议。

    模板字符串里放 markdown 是合法且常用的写法，但 markdown 中的反引号
    (行内 `code` / 代码块 ``` ``` ```) 会提前截断模板字符串导致语法错误，
    需要转义或改用 input 传入。这里根据代码内容给出针对性建议。
    """
    advices = []
    # 统计未转义反引号（跳过 \\` 转义）。执行已失败，若代码里出现反引号，
    # 大概率是 markdown 的反引号破坏了模板字符串，提示转义方向。
    count = 0
    i = 0
    while i < len(code):
        if code[i] == "\\":
            i += 2
            continue
        if code[i] == "`":
            count += 1
        i += 1
    if count:
        advices.append("markdown 中的反引号(行内 `code` / 代码块 ```)需转义为 \\` 或 \\`\\`\\`，否则会截断模板字符串")
    elif "${" in code:
        advices.append("markdown 中的 ${...} 会被当作 JS 插值求值，需写成 \\${ 保留原样")
    if advices:
        advices.append("更简单：把 markdown 文本作为 input 传入，代码里只做拼接")
    return advices


def _run_js(javascript_code, *args):
    """执行 JS 并返回结果；失败时抛出带可读中文信息的异常。

    优先使用常驻 Node 引擎；找不到 node 时回退 PyExecJS。
    """
    safe_args = [_json_safe(a) for a in args]
    engine = _get_engine()
    try:
        if engine is not None:
            return engine.call(javascript_code, safe_args)
        # 回退：PyExecJS（注意其 compile 是惰性的，语法错误在 call 时抛出）
        full_code = f"function get_result(input1, input2, input3, input4, input5, input6){{\n{javascript_code}\n}}"
        ctx = _get_runtime().compile(full_code)
        return ctx.call("get_result", *safe_args)
    except Exception as e:
        err = _extract_js_error(e)
        md = _check_markdown(javascript_code)
        msg = f"JS 执行失败: {err}"
        if md:
            msg += "\n提示: " + "；".join(md) + "。本节点只接受纯 JavaScript。"
        advice = _markdown_advice(javascript_code)
        if advice:
            msg += "\n修复建议: " + "；".join(advice) + "。"
        raise RuntimeError(msg) from e


class JavascriptExecutor:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "enable": (["On", "Off"], {"default":"On"}),
                "javascript_code": ("STRING", {"default": default_code, "multiline": True, "dynamicPrompts": False}),
            },
            "optional": {
              "input1": (any_type, {}),
              "input2": (any_type, {}),
              "input3": (any_type, {}),
              "input4": (any_type, {}),
              "input5": (any_type, {}),
              "input6": (any_type, {}),
             }
        }

    
    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ('output',)
    FUNCTION = "eval"
    CATEGORY = "ComfyUI JS"

    def eval(self, enable, javascript_code, input1 = None, input2 = None, input3 = None, input4 = None, input5 = None, input6 = None):
        if enable == "Off":
            return (None,)
        res = _run_js(javascript_code, input1, input2, input3, input4, input5, input6)
        return (res,)

class JavascriptExecutorMultiOutput:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "enable": (["On", "Off"], {"default":"On"}),
                "javascript_code": ("STRING", {"default": multi_code, "multiline": True, "dynamicPrompts": False}),
            },
            "optional": {
              "input1": (any_type, {}),
              "input2": (any_type, {}),
              "input3": (any_type, {}),
              "input4": (any_type, {}),
              "input5": (any_type, {}),
              "input6": (any_type, {}),
             }
        }

    
    RETURN_TYPES = (any_type, any_type, any_type, any_type, any_type, any_type)
    RETURN_NAMES = ('output1', 'output2', 'output3', 'output4', 'output5', 'output6')
    FUNCTION = "eval"
    CATEGORY = "ComfyUI JS"

    def eval(self, enable, javascript_code, input1 = None, input2 = None, input3 = None, input4 = None, input5 = None, input6 = None):
        if enable == "Off":
            return (None, None, None, None, None, None)
        res = _run_js(javascript_code, input1, input2, input3, input4, input5, input6)
        if isinstance(res, list):
            # 数组可能不足 6 个元素，补齐 None 避免 IndexError
            padded = (res + [None] * 6)[:6]
            return tuple(padded)
        return (res, res, res, res, res, res)

NODE_CLASS_MAPPINGS = {
    "JavascriptExecutor": JavascriptExecutor,
    "JavascriptExecutorMultiOutput": JavascriptExecutorMultiOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "JavascriptExecutor": "Javascript Executor",
    "JavascriptExecutorMultiOutput": "Javascript Executor Multi Output",
}
