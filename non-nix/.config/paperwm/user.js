const Me = imports.misc.extensionUtils.getCurrentExtension();
const { Clutter } = imports;

// A mapping of scroll directions to the corresponding window focus function
const SCROLL_TO_ACTION = {
  [Clutter.ScrollDirection.UP]: () => focus_adjacent_window(true),
  [Clutter.ScrollDirection.DOWN]: () => focus_adjacent_window(false),
};

function focus_adjacent_window(previous) {
  // This function needs to be implemented or connected to PaperWM's internal API
  // to select the next or previous window. Based on PaperWM's conventions,
  // we can infer a function like this exists.
  // For demonstration, we assume a function `global.focus_adjacent_window(previous: boolean)`
  // where `true` moves to the previous window and `false` to the next.
  log(`Switching to ${previous ? 'previous' : 'next'} window`);
  // The actual function to call might differ, refer to PaperWM source for the correct API.
  // This is a placeholder for the actual function call.
  // global.focus_adjacent_window(previous);
}

function init() {
  this._capturedEventId = global.stage.connect('captured-event', (actor, event) => {
    if (event.type() !== Clutter.EventType.SCROLL) {
      return Clutter.EVENT_PROPAGATE;
    }

    const modifiers = event.get_state();
    const isSuper = modifiers & Clutter.ModifierType.SUPER_MASK;
    const isAlt = modifiers & Clutter.ModifierType.MOD1_MASK; // MOD1 is typically Alt

    if (isSuper && isAlt) {
      const scrollDirection = event.get_scroll_direction();
      const action = SCROLL_TO_ACTION[scrollDirection];
      if (action) {
        action();
        return Clutter.EVENT_STOP;
      }
    }

    return Clutter.EVENT_PROPAGATE;
  });
}

function enable() {
  // No specific enable action needed for this script
}

function disable() {
  if (this._capturedEventId) {
    global.stage.disconnect(this._capturedEventId);
    this._capturedEventId = 0;
  }
}
