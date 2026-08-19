# ComfyUI_JS

## 功能简述

可以运行JavaScript代码的ComfyUI自定义节点，输入JavaScript代码，输出运行结果

## 使用注意

- `javascript_code` 输入框只接受**纯 JavaScript** 代码，不能直接粘贴 markdown 文本
  （如 `# 标题`、`**加粗**`、`- 列表`、``` ``` ``` 代码块围栏等）。
  若误粘贴，节点会报错并提示疑似 markdown 的行号。
- 输入框中的代码会被包进 `function get_result(input1 ~ input6) { ... }`，
  因此请直接写函数体语句（可用 `return` 返回结果），不要再写 `function` 声明；
  参数 `input1 ~ input6` 直接可用。
- 输入参数 `input1 ~ input6` 为任意类型。若接入 IMAGE/tensor 等无法直接
  序列化的对象，节点会自动降级为 `tolist()`/`str()` 后传入。
- 返回值会经 JSON 往返，`undefined`/`NaN` 等会变成 `None`；`BigInt` 不支持。

## 在模板字符串中拼接 markdown

用反引号 `` ` `` 模板字符串放多行 markdown 是支持的（标题/加粗/列表/表格/引用
都能正常输出），但要注意 markdown 与 JS 语法的三个冲突：

- **markdown 含反引号**（行内 `code`、代码块 ``` ``` ```）：会提前截断模板字符串
  导致语法错误，需转义为 `` \` `` / `` \`\`\` ``；
- **markdown 含 `${...}`**：会被当作 JS 插值求值（如 `` `${100}` `` 变成 `100`），
  想保留原样需写成 `` \${ ``；
- **markdown 含反斜杠**：`\n`、`\t`、`\\` 等会被转义解释。

若 markdown 是动态内容（AI 输出、文本节点等），**最稳妥的做法是把它接到
`input1 ~ input6` 传入，代码里只写拼接逻辑**——所有特殊字符原样保留，无需转义：

```js
// input1 = 大段 markdown 文本
return input1 + '\n\n---\n\n' + input2;
```

执行失败时，节点会在报错信息中给出针对性的修复建议（转义反引号 / 用 input 传入）。

## 性能

- 节点内部使用**常驻 Node 进程**（JSON 行协议 + 代码编译缓存），
  多次执行 / 循环调用时无需反复启动子进程，速度较传统 execjs 方式提升
  数十倍；代码变更会自动重新编译，进程意外退出会自动重启。
- `console.log` 等调试输出会转发到服务端日志，不影响节点返回值。
- 若运行环境没有 `node`，会自动回退到 PyExecJS 执行。

## 工作流举例

单路输出：
![workflow.png](example_workflows%2Fexample.png)

多路输出：
![workflow.png](example_workflows%2Fmulti_output.png)
