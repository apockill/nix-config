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
import sys


class TDirStatView(Frame):
    def __init__(self, screen):
        super(TDirStatView, self).__init__(
            screen, screen.height, screen.width, has_border=False,
            name="My Form")

        # Create the (very simple) form layout...
        layout = Layout([1], fill_frame=True)
        self.add_layout(layout)

        # Now populate it with the widgets we want to use.
        self._details = Text()
        self._details.disabled = True
        self._details.custom_colour = "field"
        titles = ["Name", "%", "Size", "Items"]
        columns = [0] + [f"{len(title) + 5}>" for title in titles[1:]]
        self._list = MultiColumnListBox(
            height=Widget.FILL_FRAME,
            columns=columns,
            titles=titles,
            options=[],
            name="qdirstat_list",
            on_select=self.popup,
            on_change=self.details)
        layout.add_widget(Label("Local disk browser sample"))
        layout.add_widget(Divider())
        layout.add_widget(self._list)
        layout.add_widget(Divider())
        layout.add_widget(self._details)
        layout.add_widget(Label("Press Enter to select or `q` to quit."))

        # Prepare the Frame for use.
        self.fix()

    def popup(self):
        # Just confirm whenever the user actually selects something.
        self._scene.add_effect(
            PopUpDialog(self._screen,
                        "You selected: {}".format(self._list.value), ["OK"]))

    def details(self):
        print("Changing _details value")
        self._details.value = "Haha I have been changed indeed"

    def process_event(self, event):
        # Do the key handling for this Frame.
        if isinstance(event, KeyboardEvent):
            if event.key_code in [ord('q'), ord('Q'), Screen.ctrl("c")]:
                raise StopApplication("User quit")

        # Now pass on to lower levels for normal handling of the event.
        return super(TDirStatView, self).process_event(event)


def demo(screen, old_scene):
    screen.play([Scene([TDirStatView(screen)], -1)], stop_on_resize=True,
                start_scene=old_scene)


"""Notes
os.stat will give
    - Size
    
def root_path():
    '''Get the root directory (os independent)'''
    return os.path.abspath(os.sep)
"""

last_scene = None
while True:
    try:
        Screen.wrapper(demo, catch_interrupt=False, arguments=[last_scene])
        sys.exit(0)
    except ResizeScreenError as e:
        last_scene = e.scene
