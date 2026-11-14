import 'package:flutter/material.dart';

import '../tokens.dart';
import 'buttons.dart';
import 'focus_reveal.dart';

/// A short form shown from `showDialog`. It is a normal [AlertDialog] when the
/// screen has room, and a full-screen form when the free height is too small
/// for the fields (landscape + keyboard + large text on a phone).
///
/// Full-screen mode keeps Cancel/Save in the app bar, so they are always
/// reachable. Its body scrolls, and the focused field is scrolled above the
/// keyboard. The fields keep their State (text, focus) when the presentation
/// changes because they live under one [GlobalKey]. Once full-screen, the form
/// stays full-screen until it closes, so opening the keyboard cannot make it
/// flip back and forth.
///
/// The caller still owns the controllers, validation and the result.
class AdaptiveFormDialog extends StatefulWidget {
  const AdaptiveFormDialog({
    super.key,
    required this.title,
    required this.fields,
    required this.confirmLabel,
    required this.onConfirm,
    this.cancelLabel = 'Huỷ',
    this.onCancel,
  });

  final String title;
  final List<Widget> fields;
  final String confirmLabel;
  final VoidCallback? onConfirm;
  final String cancelLabel;

  /// Defaults to popping the route with no result.
  final VoidCallback? onCancel;

  /// Height (dp, at text scale 1) a dialog needs besides the fields: title,
  /// action row and dialog insets.
  static const double chromeHeight = 200;

  /// Height (dp, at text scale 1) one outlined text field needs, with spacing.
  static const double fieldHeight = 80;

  /// Whether [fieldCount] fields fit a normal dialog in [media].
  static bool fitsDialog(MediaQueryData media, int fieldCount) {
    final free = freeHeightOf(media);
    final scale = media.textScaler.scale(1).clamp(1.0, 2.0);
    return free >= (chromeHeight + fieldHeight * fieldCount) * scale;
  }

  @override
  State<AdaptiveFormDialog> createState() => _AdaptiveFormDialogState();
}

class _AdaptiveFormDialogState extends State<AdaptiveFormDialog> {
  final _fieldsKey = GlobalKey(debugLabel: 'adaptive-form-fields');
  bool _fullScreen = false;

  void _cancel() => widget.onCancel != null
      ? widget.onCancel!()
      : Navigator.of(context).maybePop();

  @override
  Widget build(BuildContext context) {
    final media = MediaQuery.of(context);
    if (!_fullScreen &&
        !AdaptiveFormDialog.fitsDialog(media, widget.fields.length)) {
      _fullScreen = true; // latched for the life of this form
    }
    final fields = Column(
      key: _fieldsKey,
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < widget.fields.length; i++) ...[
          if (i > 0) const SizedBox(height: AppSpacing.xs),
          widget.fields[i],
        ],
      ],
    );
    if (!_fullScreen) {
      return AlertDialog(
        scrollable: true,
        title: Text(widget.title),
        content: fields,
        actions: [
          TextButton(onPressed: _cancel, child: Text(widget.cancelLabel)),
          PrimaryButton(
            label: widget.confirmLabel,
            expanded: false,
            onPressed: widget.onConfirm,
          ),
        ],
      );
    }
    return Dialog.fullscreen(
      child: Scaffold(
        // The body shrinks above the keyboard; the app bar (with the
        // actions) never does.
        resizeToAvoidBottomInset: true,
        appBar: AppBar(
          // 48 dp keeps the minimum touch target and leaves the most room
          // above a landscape keyboard (~100 dp free on a phone).
          toolbarHeight: kMinInteractiveDimension,
          leading: IconButton(
            icon: const Icon(Icons.close),
            tooltip: widget.cancelLabel,
            onPressed: _cancel,
          ),
          title: Text(widget.title),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: AppSpacing.xs),
              child: TextButton(
                // The default primary green is unreadable on the dark header
                // (seen on the phone); use the header's own foreground.
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.onHeaderPrimary,
                  textStyle: const TextStyle(fontWeight: FontWeight.w700),
                ),
                onPressed: widget.onConfirm,
                child: Text(widget.confirmLabel),
              ),
            ),
          ],
        ),
        body: SafeArea(
          top: false,
          child: SingleChildScrollView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.manual,
            padding: const EdgeInsets.all(AppSpacing.md),
            child: FocusReveal(child: fields),
          ),
        ),
      ),
    );
  }
}
