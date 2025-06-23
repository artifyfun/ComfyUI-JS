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

class AlwaysEqualProxy(str):
    def __eq__(self, _):
        return True

    def __ne__(self, _):
        return False

any_type = AlwaysEqualProxy("*")

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
        full_code = f"function get_result(input1, input2, input3, input4, input5, input6){{{javascript_code}}}"
        ctx = execjs.compile(full_code)
        res = ctx.call("get_result", input1, input2, input3, input4, input5, input6)
        return (res,)

NODE_CLASS_MAPPINGS = {
    "JavascriptExecutor": JavascriptExecutor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "JavascriptExecutor": "Javascript Executor",
}