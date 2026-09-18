import numpy as np

from mock.mock_camera import MockCamera


def test_mock_camera_returns_uint16_gaussian() -> None:
    camera = MockCamera(shape=(80, 100), seed=42)
    camera.connect()
    image = camera.grab_image()
    assert image.shape == (80, 100)
    assert image.dtype == np.uint16
    assert image[40, 50] > image[0, 0]

