import execjs

default_code = r"""
  // input any
  // return any
  function convertToUpperCase(str = '') {
    if (typeof str !== 'string') {
      str = str.toString();
    }
    return str.toUpperCase();
  }
  return convertToUpperCase(input)
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
                "input": (any_type, {}),
                "javascript_code": ("STRING", {"default": default_code, "multiline": True, "dynamicPrompts": False}),
            },
        }

    
    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ('output',)
    FUNCTION = "eval"
    CATEGORY = "ComfyUI JS"

    def eval(self, enable, input, javascript_code):
        if enable == "Off":
            return (input,)
        full_code = f"function get_result(input){{{javascript_code}}}"
        ctx = execjs.compile(full_code)
        res = ctx.call("get_result", input)
        return (res,)


NODE_CLASS_MAPPINGS = {
    "JavascriptExecutor": JavascriptExecutor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "JavascriptExecutor": "Javascript Executor",
}