import unittest

from led_feedback import (
    PATTERNS,
    led_pattern_on,
    runpod_processor_ready,
    service_feedback_pattern,
)


class LedFeedbackTests(unittest.TestCase):
    def test_runpod_starting_is_four_short_flashes_then_one_second_off(self):
        pattern = PATTERNS['runpod_starting']
        samples = (
            (0.05, True),
            (0.15, False),
            (0.25, True),
            (0.35, False),
            (0.45, True),
            (0.55, False),
            (0.65, True),
            (0.80, False),
            (1.65, False),
            (1.75, True),
        )
        for elapsed, expected in samples:
            with self.subTest(elapsed=elapsed):
                self.assertEqual(led_pattern_on(pattern, elapsed), expected)

    def test_hardware_and_network_errors_take_priority_over_runpod_starting(self):
        self.assertEqual(
            service_feedback_pattern(False, True, True, 'HOME', 'starting', True),
            'network_error',
        )
        self.assertEqual(
            service_feedback_pattern(True, False, True, 'HOME', 'starting', True),
            'camera_error',
        )
        self.assertEqual(
            service_feedback_pattern(True, True, False, 'HOME', 'starting', True),
            'plotter_error',
        )
        self.assertEqual(
            service_feedback_pattern(True, True, True, 'HOME', 'starting', True),
            'runpod_starting',
        )
        self.assertIsNone(
            service_feedback_pattern(True, True, True, 'HOME', 'running', True)
        )

    def test_processor_wait_never_falls_through_to_solid_ready_state(self):
        for status, desired_running in (
            (None, None),
            ('error', True),
            ('blocked', True),
            ('starting', True),
            ('stopping', True),
        ):
            with self.subTest(status=status, desired_running=desired_running):
                self.assertEqual(
                    service_feedback_pattern(
                        True,
                        True,
                        True,
                        'HOME',
                        status,
                        desired_running,
                    ),
                    'runpod_starting',
                )
                self.assertFalse(runpod_processor_ready(status))

        self.assertIsNone(
            service_feedback_pattern(True, True, True, 'HOME', 'stopped', False)
        )
        self.assertFalse(runpod_processor_ready('stopped'))
        self.assertTrue(runpod_processor_ready('running'))


if __name__ == '__main__':
    unittest.main()
