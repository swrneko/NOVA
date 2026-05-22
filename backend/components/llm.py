from llama_cpp import Llama

from config import *

class LLM():
    def __init__(self):
        '''init class'''

        print("Load model...")

        # Load model
        try:
            self.llm = Llama(
                model_path=LLM_MODEL_PATH,
                n_ctx=LLM_CONTEXT_LENTH,
                n_gpu_layers=LLM_GPU_LAYERS,
                verbose=False,
            )

            print("LLM model sucsessfully loaded!")

        except Exception as e:
            print("MODEL NOT LOADED!")
            print(f"Error when loading llm model:{e}")
        

    def llmGenerateStream(self, history: dict):
        stream = self.llm.create_chat_completion(#type: ignore
            messages=history,#type:ignore
            stream=True
        )

        for chunk in stream:
            yield chunk
