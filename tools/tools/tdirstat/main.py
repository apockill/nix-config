import sys
import os
from argparse import ArgumentParser

from asciimatics.event import KeyboardEvent
from asciimatics.widgets import (
    Frame, Layout,
    MultiColumnListBox,
    Widget,
    Label,
    PopUpDialog,
    Text,
    Divider)
from asciimatics.scene import Scene
from asciimatics.screen import Screen
from asciimatics.exceptions import ResizeScreenError, StopApplication

from crawler import DirectoryStat


class TDirStatView(Frame):
    def __init__(self, screen, dirstat: DirectoryStat):
        super(TDirStatView, self).__init__(
            screen, screen.height, screen.width, has_border=True,
            name="My Form")
        # Model
        self.dirstat = dirstat

        # Create the (very simple) form layout...
        layout = Layout([1], fill_frame=True)
        self.add_layout(layout)

        # Now populate it with the widgets we want to use.
        self._details = Text()
        self._details.disabled = True
        self._details.custom_colour = "field"
        titles = ["Name", "%", "Size", "Items"]
        columns = [0] + [f"{len(title) + 15}>" for title in titles[1:]]
        self._list = MultiColumnListBox(
            height=Widget.FILL_FRAME,
            columns=columns,
            titles=titles,
            options=[],
            name="qdirstat_list",
            on_select=self.popup,
            on_change=self.details)
        layout.add_widget(Label("TDirStat"))
        layout.add_widget(Divider())
        layout.add_widget(self._list)
        layout.add_widget(Divider())
        layout.add_widget(self._details)
        layout.add_widget(Label("Press Enter to select or `q` to quit."))

        # Prepare the Frame for use.
        self.fix()

    def update(self, frame_no):
        options = []
        for dirstat in self.dirstat.children:
            columns = [
                dirstat.path,
                "Not Implemented",
                "Not Implemented",
                str(dirstat.n_items)
            ]
            options.append((columns, "Delet this? (Not Implemented)"))
        self._list.options = options

        super().update(frame_no)

    def popup(self):
        # Just confirm whenever the user actually selects something.
        self._scene.add_effect(
            PopUpDialog(self._screen,
                        "You selected: {}".format(self._list.value), ["OK"]))

    def details(self):
        self._details.value = "Haha I have been changed indeed"

    def process_event(self, event):
        # Do the key handling for this Frame.
        if isinstance(event, KeyboardEvent):
            if event.key_code in [ord('q'), ord('Q'), Screen.ctrl("c")]:
                raise StopApplication("User quit")

        # Now pass on to lower levels for normal handling of the event.
        return super().process_event(event)


def main():
    parser = ArgumentParser()
    parser.add_argument("root_dir", default=os.getcwd(), nargs="?",
                        help="The directory to analyze")
    args = parser.parse_args()

    dirstat = None

    def demo(screen, old_scene):
        nonlocal dirstat
        if dirstat is None:
            dirstat = DirectoryStat(
                path=args.root_dir,
                on_stats_change=lambda *args, **kwargs: screen.)
        screen.play(
            [Scene([TDirStatView(screen, dirstat)], duration=-1)],

            stop_on_resize=True,
            start_scene=old_scene)

    last_scene = None
    while True:
        try:
            Screen.wrapper(demo, catch_interrupt=True, arguments=[last_scene])
            sys.exit(0)
        except ResizeScreenError as e:
            last_scene = e.scene


if __name__ == "__main__":
    main()
