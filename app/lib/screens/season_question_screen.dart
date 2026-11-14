import 'package:flutter/material.dart';

import '../design/design.dart';
import '../services/season_question_api.dart';

/// Compile-time switch for the local-QA Q&A entry point. Default OFF: a normal
/// build shows nothing new. Enable only for a local functional QA build with
/// `--dart-define=AGRICARBON_LOCAL_QA_QUESTIONS=true`. The backend route has
/// its own switch (RAG_QA_ENABLED); both must be on to get an answer.
const bool kLocalQaQuestionsEnabled =
    bool.fromEnvironment('AGRICARBON_LOCAL_QA_QUESTIONS');

/// Suggested READ-tier questions (same wording as the web farmer panel,
/// web-dashboard/src/features/aiQuestions.tsx).
const kSeasonQuestionSuggestions = <(String, SeasonQuestionIntent)>[
  ('Vụ này đang thế nào?', SeasonQuestionIntent.explain),
  ('Vụ này còn thiếu dữ liệu gì?', SeasonQuestionIntent.dataGap),
  ('Tài liệu nào nói về tưới ngập khô xen kẽ?', SeasonQuestionIntent.evidence),
  ('So với vụ trước của ruộng này thì sao?', SeasonQuestionIntent.compare),
];

const _sourceTypeLabels = {
  'guideline': 'Hướng dẫn',
  'policy': 'Chính sách',
  'methodology': 'Phương pháp luận',
  'research': 'Nghiên cứu',
  'tenant_document': 'Tài liệu nội bộ HTX',
};

/// Lower-case, strip Vietnamese diacritics, collapse spaces.
String foldVietnamese(String text) {
  const from =
      'àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ';
  const to =
      'aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd';
  final lower = text.toLowerCase();
  final out = StringBuffer();
  for (final rune in lower.runes) {
    final ch = String.fromCharCode(rune);
    final i = from.indexOf(ch);
    out.write(i >= 0 ? to[i] : ch);
  }
  return out.toString().replaceAll(RegExp(r'\s+'), ' ').trim();
}

/// Deterministic READ-tier intent hint for a typed question (no model, no
/// network); the same phrase rules as web `questionIntent.ts`, minus
/// `recommend`, which this screen never sends.
SeasonQuestionIntent? suggestSeasonQuestionIntent(String text) {
  final folded = foldVietnamese(text);
  if (folded.isEmpty) return null;
  const rules = <(SeasonQuestionIntent, List<String>)>[
    (
      SeasonQuestionIntent.dataGap,
      [
        'con thieu',
        'thieu du lieu',
        'thieu gi',
        'dang thieu',
        'bi thieu',
        'bo sung',
        'chua du',
        'chua nhap',
        'can nhap',
        'can ghi',
        'du lieu gi'
      ]
    ),
    (
      SeasonQuestionIntent.compare,
      ['so sanh', 'so voi', 'vu truoc', 'vu khac', 'chenh lech', 'hon hay kem']
    ),
    (
      SeasonQuestionIntent.evidence,
      [
        'tai lieu',
        'nguon',
        'huong dan',
        'quy trinh',
        'can cu',
        'trich dan',
        'quy dinh'
      ]
    ),
    (
      SeasonQuestionIntent.explain,
      [
        'the nao',
        'ra sao',
        'tom tat',
        'giai thich',
        'tinh hinh',
        'bao nhieu',
        'la gi'
      ]
    ),
  ];
  for (final (intent, phrases) in rules) {
    if (phrases.any(folded.contains)) return intent;
  }
  return null;
}

String seasonQuestionFailureMessage(SeasonQuestionFailure f) => switch (f) {
      SeasonQuestionFailure.offline =>
        'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.',
      SeasonQuestionFailure.timeout =>
        'Quá thời gian chờ câu trả lời. Bạn có thể thử lại.',
      SeasonQuestionFailure.unauthenticated =>
        'Phiên đăng nhập đã hết. Hãy đăng nhập lại.',
      SeasonQuestionFailure.notFound =>
        'Không tìm thấy vụ, hoặc bạn không có quyền xem vụ này.',
      SeasonQuestionFailure.invalid =>
        'Câu hỏi chưa hợp lệ. Hãy viết ngắn gọn hơn và chọn loại câu hỏi.',
      SeasonQuestionFailure.disabled =>
        'Trợ lý hỏi đáp chưa được bật cho hệ thống này.',
      SeasonQuestionFailure.generationUnavailable =>
        'Loại câu hỏi này cần trợ lý AI, hiện chưa sẵn sàng. Hãy chọn loại câu hỏi khác.',
      SeasonQuestionFailure.citationBlocked =>
        'Câu trả lời bị chặn vì không qua được bước kiểm tra nguồn dẫn. Bạn có thể thử lại.',
      SeasonQuestionFailure.quota =>
        'Đã đạt giới hạn lượt hỏi cho hôm nay. Vui lòng thử lại sau.',
      SeasonQuestionFailure.server =>
        'Hệ thống chưa trả lời được. Vui lòng thử lại.',
    };

/// Ask one READ-tier question about one synced crop season. Nothing is stored:
/// the last answer lives in this State only and is dropped when the screen is
/// closed, when the season changes or when the signed-in account changes.
class SeasonQuestionScreen extends StatefulWidget {
  const SeasonQuestionScreen({
    super.key,
    required this.asker,
    required this.cropSeasonId,
    required this.seasonLabel,
    this.scope,
    this.scopeKey,
    this.banner,
  });

  final SeasonQuestionAsker asker;

  /// Server `crop_seasons.id` (never a local client id).
  final String cropSeasonId;
  final String seasonLabel;

  /// Notifies on auth changes; [scopeKey] returns the current account id (or
  /// null when signed out). A different key closes the screen.
  final Listenable? scope;
  final String? Function()? scopeKey;

  /// Optional notice shown above the form (the UI preview labels its fixture).
  final Widget? banner;

  @override
  State<SeasonQuestionScreen> createState() => _SeasonQuestionScreenState();
}

sealed class _View {
  const _View();
}

class _Idle extends _View {
  const _Idle();
}

class _Loading extends _View {
  const _Loading(this.question);
  final String question;
}

class _Answered extends _View {
  const _Answered(this.question, this.answer);
  final String question;
  final SeasonQuestionAnswer answer;
}

class _Failed extends _View {
  const _Failed(this.question, this.intent, this.error);
  final String question;
  final SeasonQuestionIntent intent;
  final SeasonQuestionException error;
}

class _SeasonQuestionScreenState extends State<SeasonQuestionScreen> {
  final _controller = TextEditingController();
  SeasonQuestionIntent _intent = SeasonQuestionIntent.explain;
  bool _intentChosen = false;
  SeasonQuestionIntent? _autoPicked;
  _View _view = const _Idle();
  SeasonQuestionRequest? _inFlight;
  int _generation = 0;
  String? _scopeAtOpen;

  @override
  void initState() {
    super.initState();
    _scopeAtOpen = widget.scopeKey?.call();
    widget.scope?.addListener(_onScopeChanged);
  }

  @override
  void didUpdateWidget(SeasonQuestionScreen old) {
    super.didUpdateWidget(old);
    if (old.cropSeasonId != widget.cropSeasonId) _reset();
    if (old.scope != widget.scope) {
      old.scope?.removeListener(_onScopeChanged);
      widget.scope?.addListener(_onScopeChanged);
    }
  }

  @override
  void dispose() {
    widget.scope?.removeListener(_onScopeChanged);
    _generation++;
    _inFlight?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _reset() {
    _generation++;
    _inFlight?.cancel();
    _inFlight = null;
    setState(() => _view = const _Idle());
  }

  void _onScopeChanged() {
    if (widget.scopeKey?.call() == _scopeAtOpen) return;
    // Account signed out or switched: drop everything and leave.
    _reset();
    if (mounted) Navigator.of(context).maybePop();
  }

  Future<void> _ask(String text, SeasonQuestionIntent intent) async {
    final question = text.trim();
    if (question.isEmpty) return;
    FocusScope.of(context).unfocus();
    _inFlight?.cancel();
    final mine = ++_generation;
    final request = widget.asker
        .ask(widget.cropSeasonId, question: question, intent: intent);
    _inFlight = request;
    setState(() => _view = _Loading(question));
    try {
      final answer = await request.future;
      if (!mounted || mine != _generation) return;
      if (answer.cropSeasonId != widget.cropSeasonId) {
        setState(() => _view = _Failed(question, intent,
            const SeasonQuestionException(SeasonQuestionFailure.server)));
        return;
      }
      setState(() => _view = _Answered(question, answer));
    } on SeasonQuestionCancelled {
      return;
    } on SeasonQuestionException catch (e) {
      if (!mounted || mine != _generation) return;
      setState(() => _view = _Failed(question, intent, e));
    } finally {
      if (identical(_inFlight, request)) _inFlight = null;
    }
  }

  void _onChanged(String text) {
    if (_intentChosen) return;
    final hint = suggestSeasonQuestionIntent(text);
    setState(() {
      if (hint != null) _intent = hint;
      _autoPicked = hint;
    });
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final busy = _view is _Loading;
    return AppScaffold(
      header: AppHeader(
        title: 'Hỏi đáp về vụ mùa',
        subtitle: widget.seasonLabel,
        showBackButton: true,
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (widget.banner != null) ...[
            widget.banner!,
            const SizedBox(height: AppSpacing.md),
          ],
          Text(
            'Câu trả lời chỉ dùng số liệu đã ghi nhận của vụ và tài liệu đã được duyệt. Hệ thống không lưu câu hỏi.',
            style: text.bodyMedium?.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.md),
          Text('Câu hỏi gợi ý', style: text.titleSmall),
          const SizedBox(height: AppSpacing.xs),
          // Full-width, wrapping buttons: chips cannot wrap a long
          // Vietnamese question and overflow at 320 dp.
          for (final (q, intent) in kSeasonQuestionSuggestions)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  alignment: Alignment.centerLeft,
                  minimumSize: const Size.fromHeight(48),
                  padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
                ),
                icon: const Icon(Icons.chat_bubble_outline, size: 18),
                label: Text(q, textAlign: TextAlign.start),
                onPressed: busy
                    ? null
                    : () {
                        _controller.text = q;
                        setState(() {
                          _intent = intent;
                          _autoPicked = null;
                        });
                        _ask(q, intent);
                      },
              ),
            ),
          const SizedBox(height: AppSpacing.md),
          Text('Loại câu hỏi', style: text.titleSmall),
          const SizedBox(height: AppSpacing.xxs),
          for (final i in SeasonQuestionIntent.values)
            _IntentOption(
              intent: i,
              selected: _intent == i,
              onSelect: busy
                  ? null
                  : () => setState(() {
                        _intent = i;
                        _intentChosen = true;
                        _autoPicked = null;
                      }),
            ),
          const SizedBox(height: AppSpacing.md),
          TextField(
            key: const Key('season-question-input'),
            controller: _controller,
            enabled: !busy,
            maxLength: 2000,
            minLines: 2,
            maxLines: 5,
            textInputAction: TextInputAction.send,
            onChanged: _onChanged,
            onSubmitted: (v) => _ask(v, _intent),
            decoration: const InputDecoration(
              labelText: 'Câu hỏi của bạn',
              hintText: 'Ví dụ: Vụ này còn thiếu dữ liệu gì?',
            ),
          ),
          if (_autoPicked != null)
            Text(
              'Đã chọn loại câu hỏi “${_autoPicked!.label}” theo nội dung câu hỏi. Bạn có thể đổi.',
              style: text.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
          const SizedBox(height: AppSpacing.sm),
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: _controller,
            builder: (context, value, _) => PrimaryButton(
              label: busy ? 'Đang trả lời…' : 'Gửi câu hỏi',
              icon: Icons.send_outlined,
              loading: busy,
              onPressed: busy || value.text.trim().isEmpty
                  ? null
                  : () => _ask(value.text, _intent),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          _result(context),
        ],
      ),
    );
  }

  Widget _result(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return switch (_view) {
      _Idle() => const SizedBox.shrink(),
      _Loading() => Semantics(
          liveRegion: true,
          child: LoadingState(message: 'Đang soạn câu trả lời…'),
        ),
      _Failed(:final question, :final intent, :final error) => AppCard(
          variant: AppCardVariant.highlight,
          child: Semantics(
            liveRegion: true,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(children: [
                  const ExcludeSemantics(
                      child: Icon(Icons.error_outline, color: AppColors.error)),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: Text(seasonQuestionFailureMessage(error.failure),
                        style: text.bodyMedium),
                  ),
                ]),
                if (error.retryable) ...[
                  const SizedBox(height: AppSpacing.sm),
                  SecondaryButton(
                    label: 'Thử lại',
                    icon: Icons.refresh,
                    expanded: true,
                    onPressed: () => _ask(question, intent),
                  ),
                ],
              ],
            ),
          ),
        ),
      _Answered(:final question, :final answer) =>
        _AnswerCard(question: question, answer: answer),
    };
  }
}

class _IntentOption extends StatelessWidget {
  const _IntentOption(
      {required this.intent, required this.selected, required this.onSelect});
  final SeasonQuestionIntent intent;
  final bool selected;
  final VoidCallback? onSelect;

  @override
  Widget build(BuildContext context) => Semantics(
        selected: selected,
        inMutuallyExclusiveGroup: true,
        button: true,
        child: InkWell(
          onTap: onSelect,
          borderRadius: AppRadii.allField,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Row(children: [
              ExcludeSemantics(
                child: Icon(
                  selected
                      ? Icons.radio_button_checked
                      : Icons.radio_button_unchecked,
                  color: selected ? AppColors.primary : AppColors.controlLine,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                  child: Text(intent.label,
                      style: Theme.of(context).textTheme.bodyLarge)),
            ]),
          ),
        ),
      );
}

class _AnswerCard extends StatelessWidget {
  const _AnswerCard({required this.question, required this.answer});
  final String question;
  final SeasonQuestionAnswer answer;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final intentLabel =
        SeasonQuestionIntent.fromWire(answer.intent)?.label ?? answer.intent;
    return AppCard(
      child: Semantics(
        liveRegion: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Câu hỏi: $question',
                style:
                    text.bodySmall?.copyWith(color: AppColors.textSecondary)),
            const SizedBox(height: AppSpacing.xs),
            // Not StatusBadge: its single-line Row overflows at 320 dp with
            // enlarged text; this label wraps.
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const ExcludeSemantics(
                  child: Icon(Icons.verified_outlined,
                      size: 18, color: AppColors.primary)),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: Text(
                  '${answer.systemComposed ? 'Hệ thống soạn — không dùng AI' : 'Trợ lý AI viết'} · Loại: $intentLabel',
                  style: text.labelMedium?.copyWith(color: AppColors.primary),
                ),
              ),
            ]),
            const SizedBox(height: AppSpacing.md),
            if (answer.insufficient) ...[
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const ExcludeSemantics(
                    child:
                        Icon(Icons.info_outline, color: AppColors.warningText)),
                const SizedBox(width: AppSpacing.xs),
                Expanded(
                  child: Text(
                    answer.insufficientReason ??
                        'Chưa đủ dữ liệu hoặc tài liệu đã duyệt để trả lời câu hỏi này.',
                    style:
                        text.bodyMedium?.copyWith(color: AppColors.warningText),
                  ),
                ),
              ]),
              const SizedBox(height: AppSpacing.sm),
            ],
            if (answer.answer != null && answer.answer!.isNotEmpty)
              SelectableText(answer.answer!, style: text.bodyLarge),
            if (answer.systemComposed) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(
                'Hệ thống tự soạn từ số liệu đã ghi nhận, không dùng mô hình AI. Đây là câu trả lời theo mẫu cố định của loại câu hỏi đã chọn.',
                style: text.bodySmall?.copyWith(color: AppColors.textSecondary),
              ),
            ],
            if (answer.limitations.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.md),
              Text('Giới hạn', style: text.titleSmall),
              for (final l in answer.limitations)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.xxs),
                  child: Text('• $l', style: text.bodySmall),
                ),
            ],
            if (answer.citations.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.md),
              Text('Nguồn trích dẫn', style: text.titleSmall),
              for (final c in answer.citations)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.xs),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const ExcludeSemantics(
                          child: Icon(Icons.menu_book_outlined,
                              size: 18, color: AppColors.primary)),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: Text(
                          [
                            c.title,
                            if (c.section != null && c.section!.isNotEmpty)
                              c.section!,
                            _sourceTypeLabels[c.sourceType] ?? c.sourceType,
                          ].join(' · '),
                          style: text.bodySmall,
                        ),
                      ),
                    ],
                  ),
                ),
            ] else if (!answer.insufficient) ...[
              const SizedBox(height: AppSpacing.md),
              Text('Câu trả lời này không trích dẫn tài liệu.',
                  style:
                      text.bodySmall?.copyWith(color: AppColors.textSecondary)),
            ],
          ],
        ),
      ),
    );
  }
}
