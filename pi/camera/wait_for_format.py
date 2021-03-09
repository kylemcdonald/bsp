from flushed import log
import cv2
import time

def wait_for_format(fourcc, width, height, fps, port=0):
    while True:
        log(f'camera> connecting to port {port}: {fourcc} {width} x {height} @ {fps}fps')
        camera = cv2.VideoCapture(port)
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        camera.set(cv2.CAP_PROP_FPS, fps)
        camera.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        camera.set(cv2.CAP_PROP_FOCUS, 0)
        if not camera.isOpened():
            log('camera> port not opening')
        else:
            log('camera> port open')
            status, img = camera.read()
            if status:
                current_width = camera.get(3)
                current_height = camera.get(4)
                log(f'camera> reading at {current_width} x {current_height}')
                if current_width >= width and current_height >= height:
                    log('camera> resolution met')
                    return camera
                else:
                    log('camera> resolution not met')
            else:
                log('camera> not reading')
        log('camera> releasing camera')
        camera.release()
        log('camera> wait_for_format sleeping')
        time.sleep(10)

if __name__ == '__main__':
    print('waiting for 4k')
    camera = wait_for_format('MJPG', 3840, 2160, 5)
    print('got 4k')