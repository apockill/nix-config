def test_opencv():
    import cv2, numpy as np

    empty_image = np.zeros((100, 120), dtype=np.uint8)
    cv2.imshow("A window", empty_image)
    for _ in range(3):
        cv2.waitKey(1)
    cv2.destroyAllWindows()

def test_torch():
    import torch
    assert torch.cuda.is_available(), "No CUDA-compatible GPU found!"


def test_genesis():
    """Validate genesis can open a window (which requires a OpenGL context to work)"""

    import genesis as gs

    gs.init(backend=gs.gpu)

    scene = gs.Scene(show_viewer=True)
    plane = scene.add_entity(gs.morphs.Plane())
    scene.build()

    for _ in range(10):
        scene.step()


def test_pillow():
    """Validate pillow was able to install at all, which requires certain libraries"""
    import PIL

def test_gymnasium():
    """A basic test of gym that ensures SWIG and clang are installed, and that it can
    correctly spin up and run a gym"""
    import gymnasium as gym

    env = gym.make("LunarLander-v3", render_mode="human")
    observation, info = env.reset()

    episode_over = False
    for _ in range(3):
        action = env.action_space.sample()  # agent policy that uses the observation and info
        assert action is not None
        observation, reward, terminated, truncated, info = env.step(action)

        episode_over = terminated or truncated

    env.close()