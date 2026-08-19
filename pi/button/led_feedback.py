PATTERNS = {
    'capturing': {'pulses': None, 'on': 0.25, 'off': 0.25, 'pause': 0},
    'network_error': {'pulses': 1, 'on': 0.1, 'off': 0.1, 'pause': 1.0},
    'camera_error': {'pulses': 2, 'on': 0.1, 'off': 0.1, 'pause': 1.0},
    'plotter_error': {'pulses': 3, 'on': 0.1, 'off': 0.1, 'pause': 1.0},
    'runpod_starting': {'pulses': 4, 'on': 0.1, 'off': 0.1, 'pause': 1.0},
    'restart_ready': {'pulses': None, 'on': 0.2, 'off': 0.2, 'pause': 0},
}


def service_feedback_pattern(
    network_ready,
    camera_ready,
    plotter_ready,
    plotter_state,
    runpod_status,
    runpod_desired_running,
):
    if not network_ready:
        return 'network_error'
    if not camera_ready:
        return 'camera_error'
    if not plotter_ready or plotter_state == 'ERROR':
        return 'plotter_error'
    if not runpod_processor_ready(runpod_status) and runpod_desired_running is not False:
        return 'runpod_starting'
    return None


def runpod_processor_ready(runpod_status):
    return runpod_status == 'running'


def led_pattern_on(pattern, elapsed):
    pulses = pattern['pulses']
    on_duration = pattern['on']
    off_duration = pattern['off']
    if pulses is None:
        cycle = on_duration + off_duration
        return elapsed % cycle < on_duration
    active_duration = pulses * on_duration + (pulses - 1) * off_duration
    cycle = active_duration + pattern['pause']
    pos = elapsed % cycle
    if pos >= active_duration:
        return False
    pulse_span = on_duration + off_duration
    return pos % pulse_span < on_duration
