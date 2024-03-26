import execjs

text2text_code = r"""
  function replaceUnderline(str) {
    return str.replace(/_/g, ' ');
  }
  return replaceUnderline(text + ', ' + 'test for ComfyUI_JS!')
"""

class Text2Text:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "enable": (["On", "Off"], {"default":"On"}),
                "text": ("STRING", {"forceInput": True}),
                "javascript_code": ("STRING", {"default": text2text_code, "multiline": True, "dynamicPrompts": False}),
            },
        }

    
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('text',)
    FUNCTION = "eval"
    CATEGORY = "ComfyUI JS"

    def eval(self, enable, text, javascript_code):
        if enable == "Off":
            return {"ui": {"text": text}, "result": (text,)}
        full_code = f"function get_result(text){{{javascript_code}}}"
        ctx = execjs.compile(full_code)
        res = ctx.call("get_result", text)
        return {"ui": {"text": res}, "result": (res,)}


class TextInput:
    def __init__(self):
      pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
                    "text": ("STRING", {"default": "text strings", "multiline": True}),
                    },
                }

    RETURN_TYPES = ("STRING", )
    RETURN_NAMES = ("text", )
    FUNCTION = "get_value"
    CATEGORY = "ComfyUI JS"

    def get_value(self, text):
        return (text,)


NODE_CLASS_MAPPINGS = {
    "Text2Text": Text2Text,
    "TextInput": TextInput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Text2Text": "Text to Text",
    "TextInput": "Text Input",
}