import execjs

default_code = r"""
  function convertToUpperCase(str = '') {
    return str.toUpperCase();
  }
  return convertToUpperCase(input_string)
"""

class JavascriptExecutor:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "enable": (["On", "Off"], {"default":"On"}),
                "input_string": ("STRING", {"forceInput": False}),
                "javascript_code": ("STRING", {"default": default_code, "multiline": True, "dynamicPrompts": False}),
            },
        }

    
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('output_string',)
    FUNCTION = "eval"
    CATEGORY = "ComfyUI JS"

    def eval(self, enable, input_string, javascript_code):
        if enable == "Off":
            return {"ui": {"input_string": input_string}, "result": (input_string,)}
        full_code = f"function get_result(input_string){{{javascript_code}}}"
        ctx = execjs.compile(full_code)
        res = ctx.call("get_result", input_string)
        return {"ui": {"input_string": input_string}, "result": (res,)}


NODE_CLASS_MAPPINGS = {
    "JavascriptExecutor": JavascriptExecutor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "JavascriptExecutor": "Javascript Executor",
}