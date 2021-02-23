import tflite_runtime.interpreter as tflite
import numpy as np

class BlinkDetector:
    def __init__(self):
        self.interpreter = tflite.Interpreter(model_path='models/eye_blink.tflite')
        self.input_index = self.interpreter.get_input_details()[0]['index']
        self.output_index = self.interpreter.get_output_details()[0]['index']
        self.interpreter.allocate_tensors()
        
    def __call__(self, eyes):
        eyes_stacked = np.stack((eyes['left'], eyes['right']))
        eyes_stacked = (eyes_stacked.mean(-1, dtype=np.float32) / 255)[...,np.newaxis]

        self.interpreter.set_tensor(self.input_index, eyes_stacked[:1])
        self.interpreter.invoke()
        left_out = self.interpreter.get_tensor(self.output_index)[0,0]
        
        self.interpreter.set_tensor(self.input_index, eyes_stacked[1:2])
        self.interpreter.invoke()
        right_out = self.interpreter.get_tensor(self.output_index)[0,0]
        
        return (left_out + right_out) / 2