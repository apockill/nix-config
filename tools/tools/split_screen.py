from subprocess import run
from subprocess import PIPE
from typing import NamedTuple, Tuple, List


class Monitor(NamedTuple):
    name: str
    width_mm: int
    width_px: int
    height_mm: int
    height_px: int


def get_monitor_information() -> List[Monitor]:
    proc = run(["xrandr", "--listactivemonitors"], check=True, stderr=PIPE, stdout=PIPE)

    monitor_descriptions = str(proc.stdout, encoding="utf-8").split("\n")[1:]
    monitors = []
    for monitor_description in monitor_descriptions:
        monitor_description = monitor_description.strip()

        if not len(monitor_description):
            continue

        split = monitor_description.split()

        name = split[3]

        width_info, height_info = split[2].split("x")
        width_info = width_info.split("/")
        height_info = height_info.split("+")[0].split("/")

        width_px = int(width_info[0])
        width_mm = int(width_info[1])
        height_px = int(height_info[0])
        height_mm = int(height_info[1])

        monitors.append(
            Monitor(
                name=name,
                width_mm=width_mm,
                width_px=width_px,
                height_mm=height_mm,
                height_px=height_px,
            )
        )
    return monitors


def split_number(number, n_splits) -> List[int]:
    """Returns a list of numbers [n, n, n, n + remainder] where the sum
    of the list is equal to the input 'number', and the length of the list is
    n_splits."""
    number, remainder = divmod(number, n_splits)
    splits = [number for _ in range(n_splits)]
    splits[-1] += remainder
    return splits


def split_monitor(monitor: Monitor, n_splits: int):
    """Split the monitor vertically"""
    all_px_mm = zip(
        split_number(monitor.width_px, n_splits),
        split_number(monitor.width_mm, n_splits),
    )
    total_w_offset = 0
    for i, px_mm in enumerate(all_px_mm):
        w_px, w_mm = px_mm

        associate_name = monitor.name if i == 0 else "none"
        cmd = [
            "xrandr",
            "--setmonitor",
            f"{monitor.name}~{i + 1}",
            f"{w_px}/{w_mm}x{monitor.height_px}/{monitor.height_mm}"
            f"+{total_w_offset}+{0}",
            associate_name,
        ]
        total_w_offset += w_px
        run(cmd, check=True)


def main():
    monitors = get_monitor_information()
    print("Splitting monitor", monitors[0])
    split_monitor(monitors[0], n_splits=2)
    # xrandr --setmonitor "monitor_name" "width_px"/"width_mm"x"height_px"/"height_mm"+"x_offset_px"+"y_offset_px" "output_name"


if __name__ == "__main__":
    main()
