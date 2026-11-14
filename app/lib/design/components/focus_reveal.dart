import 'package:flutter/widgets.dart';

import '../tokens.dart';

/// Free height (dp) under which a screen with the keyboard open is "cramped":
/// a phone in landscape with Gboard open has ~100 dp left.
const double kCrampedFreeHeight = 260;

/// Height left for content: screen minus system bars and the keyboard.
double freeHeightOf(MediaQueryData media) =>
    media.size.height -
    media.viewPadding.top -
    media.viewPadding.bottom -
    media.viewInsets.bottom;

/// Keyboard open and too little room left for a header, a field and a button.
bool isCramped(MediaQueryData media) =>
    media.viewInsets.bottom > 0 && freeHeightOf(media) < kCrampedFreeHeight;

/// While [enabled], scrolls the focused field below [child] to the middle of
/// its scroll view whenever focus moves or the keyboard/rotation changes the
/// free area. Flutter's own caret reveal is not enough when only ~50 dp are
/// left: on a physical phone the typed line stayed under the keyboard.
class FocusReveal extends StatefulWidget {
  const FocusReveal({super.key, required this.child, this.enabled = true});

  final Widget child;
  final bool enabled;

  @override
  State<FocusReveal> createState() => _FocusRevealState();
}

class _FocusRevealState extends State<FocusReveal> with WidgetsBindingObserver {
  final _key = GlobalKey(debugLabel: 'focus-reveal');
  double? _lastInset;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    FocusManager.instance.addListener(_reveal);
  }

  @override
  void dispose() {
    FocusManager.instance.removeListener(_reveal);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeMetrics() => _reveal();

  void _reveal() {
    if (!widget.enabled) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !widget.enabled) return;
      final focused = FocusManager.instance.primaryFocus?.context;
      final scope = _key.currentContext;
      if (focused == null || scope == null || !focused.mounted) return;
      var inside = false;
      focused.visitAncestorElements((e) {
        if (e == scope) inside = true;
        return !inside;
      });
      if (!inside || Scrollable.maybeOf(focused) == null) return;
      Scrollable.ensureVisible(focused,
          alignment: 0.5, duration: AppDurations.fast);
    });
  }

  @override
  Widget build(BuildContext context) {
    final inset = MediaQuery.viewInsetsOf(context).bottom;
    if (_lastInset != inset) {
      _lastInset = inset;
      _reveal();
    }
    return KeyedSubtree(key: _key, child: widget.child);
  }
}
