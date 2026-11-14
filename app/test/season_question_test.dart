import 'dart:async';
import 'dart:convert';

import 'package:agricarbon_app/design/design.dart';
import 'package:agricarbon_app/screens/season_question_screen.dart';
import 'package:agricarbon_app/services/season_question_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import '../tool/ui_preview.dart' as preview;

Map<String, dynamic> _answerJson(String seasonId,
        {String status = 'generated', String intent = 'explain'}) =>
    {
      'status': status,
      'intent': intent,
      'mode': 'ask',
      'crop_season_id': seasonId,
      'answer': status == 'generated' ? 'Vụ đã ghi 3 hoạt động.' : null,
      'insufficient_reason':
          status == 'generated' ? null : 'Vụ chưa có dữ liệu thu hoạch.',
      'limitations': ['Chỉ dựa trên dữ liệu đã đồng bộ.'],
      'citations': [
        {
          'source_id': 's1',
          'chunk_id': 'c1',
          'document_id': 'd1',
          'title': 'Hướng dẫn AWD',
          'section': '2. Tưới',
          'source_type': 'guideline',
        }
      ],
      'trusted_facts': [],
      'provenance': {
        'answer_source': 'system_composed',
        'llm_calls': 0,
        'persisted': false
      },
    };

http.Response _json(Object body, int status) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status,
        headers: {'content-type': 'application/json'});

/// Hand-driven asker: each ask() returns a request the test completes.
class _FakeAsker implements SeasonQuestionAsker {
  final calls = <(String, String, SeasonQuestionIntent)>[];
  final pending = <Completer<SeasonQuestionAnswer>>[];
  int cancels = 0;

  @override
  SeasonQuestionRequest ask(String cropSeasonId,
      {required String question, required SeasonQuestionIntent intent}) {
    calls.add((cropSeasonId, question, intent));
    final c = Completer<SeasonQuestionAnswer>();
    pending.add(c);
    return SeasonQuestionRequest(c.future, () {
      cancels++;
      if (!c.isCompleted) c.completeError(const SeasonQuestionCancelled());
    });
  }
}

Widget _host(Widget child) =>
    MaterialApp(theme: AgriCarbonTheme.light(), home: child);

void main() {
  test('Q&A entry point is OFF unless the local-QA define is set', () {
    expect(kLocalQaQuestionsEnabled, isFalse);
  });

  group('SeasonQuestionApi', () {
    test('posts only question + READ intent with the bearer token', () async {
      late http.Request seen;
      final api = SeasonQuestionApi(() => 'jwt-x',
          baseUrl: 'http://127.0.0.1:8010',
          clientFactory: () => MockClient((r) async {
                seen = r;
                return _json(_answerJson('season-1'), 200);
              }));
      final answer = await api
          .ask('season-1',
              question: 'Vụ này thế nào?', intent: SeasonQuestionIntent.dataGap)
          .future;
      expect(seen.method, 'POST');
      expect(seen.url.toString(),
          'http://127.0.0.1:8010/v1/crop-seasons/season-1/questions');
      expect(seen.headers['Authorization'], 'Bearer jwt-x');
      expect(jsonDecode(seen.body),
          {'question': 'Vụ này thế nào?', 'intent': 'data_gap'});
      expect(answer.cropSeasonId, 'season-1');
      expect(answer.systemComposed, isTrue);
      expect(answer.citations.single.title, 'Hướng dẫn AWD');
    });

    test('READ-tier only: recommend and what_if are not offered', () {
      expect(SeasonQuestionIntent.values.map((i) => i.wire),
          ['explain', 'data_gap', 'evidence', 'compare']);
    });

    test('no token fails closed without a request', () async {
      var requests = 0;
      final api = SeasonQuestionApi(() => null,
          baseUrl: 'http://127.0.0.1:8010',
          clientFactory: () => MockClient((r) async {
                requests++;
                return _json({}, 200);
              }));
      await expectLater(
          api
              .ask('s', question: 'q', intent: SeasonQuestionIntent.explain)
              .future,
          throwsA(isA<SeasonQuestionException>().having((e) => e.failure,
              'failure', SeasonQuestionFailure.unauthenticated)));
      expect(requests, 0);
    });

    for (final (status, code, failure, retryable) in [
      (401, 'unauthenticated', SeasonQuestionFailure.unauthenticated, false),
      (404, 'not_found', SeasonQuestionFailure.notFound, false),
      (422, 'validation_error', SeasonQuestionFailure.invalid, false),
      (429, 'quota_exceeded', SeasonQuestionFailure.quota, false),
      (502, 'citation_mismatch', SeasonQuestionFailure.citationBlocked, true),
      (503, 'backend_not_configured', SeasonQuestionFailure.disabled, false),
      (
        503,
        'generation_unavailable',
        SeasonQuestionFailure.generationUnavailable,
        false
      ),
      (503, 'retrieval_unavailable', SeasonQuestionFailure.server, true),
      (500, 'rag_error', SeasonQuestionFailure.server, true),
    ]) {
      test('$status $code -> $failure', () async {
        final api = SeasonQuestionApi(() => 't',
            baseUrl: 'http://127.0.0.1:8010',
            clientFactory: () => MockClient((r) async => _json({
                  'detail': {
                    'error': {'code': code, 'message': 'x'}
                  }
                }, status)));
        await expectLater(
            api
                .ask('s', question: 'q', intent: SeasonQuestionIntent.explain)
                .future,
            throwsA(isA<SeasonQuestionException>()
                .having((e) => e.failure, 'failure', failure)
                .having((e) => e.retryable, 'retryable', retryable)));
      });
    }

    test('socket error -> offline, retryable', () async {
      final api = SeasonQuestionApi(() => 't',
          baseUrl: 'http://127.0.0.1:8010',
          clientFactory: () =>
              MockClient((r) async => throw http.ClientException('refused')));
      await expectLater(
          api
              .ask('s', question: 'q', intent: SeasonQuestionIntent.explain)
              .future,
          throwsA(isA<SeasonQuestionException>()
              .having((e) => e.failure, 'f', SeasonQuestionFailure.offline)
              .having((e) => e.retryable, 'retryable', true)));
    });

    test('cancel settles as cancelled even if the response arrives later',
        () async {
      final gate = Completer<http.Response>();
      final api = SeasonQuestionApi(() => 't',
          baseUrl: 'http://127.0.0.1:8010',
          clientFactory: () => MockClient((r) => gate.future));
      final req =
          api.ask('s', question: 'q', intent: SeasonQuestionIntent.explain);
      req.cancel();
      gate.complete(_json(_answerJson('s'), 200));
      await expectLater(req.future, throwsA(isA<SeasonQuestionCancelled>()));
    });

    test('timeout -> timeout failure', () async {
      final api = SeasonQuestionApi(() => 't',
          baseUrl: 'http://127.0.0.1:8010',
          timeout: const Duration(milliseconds: 10),
          clientFactory: () =>
              MockClient((r) => Completer<http.Response>().future));
      await expectLater(
          api
              .ask('s', question: 'q', intent: SeasonQuestionIntent.explain)
              .future,
          throwsA(isA<SeasonQuestionException>()
              .having((e) => e.failure, 'f', SeasonQuestionFailure.timeout)));
    });
  });

  test('intent hint folds Vietnamese and never yields recommend', () {
    expect(suggestSeasonQuestionIntent('Vụ này còn THIẾU dữ liệu gì?'),
        SeasonQuestionIntent.dataGap);
    expect(suggestSeasonQuestionIntent('So sánh với vụ trước'),
        SeasonQuestionIntent.compare);
    expect(suggestSeasonQuestionIntent('Có tài liệu hướng dẫn nào?'),
        SeasonQuestionIntent.evidence);
    expect(suggestSeasonQuestionIntent('Tôi nên làm gì?'), isNull);
    expect(suggestSeasonQuestionIntent(''), isNull);
  });

  group('SeasonQuestionScreen', () {
    testWidgets('suggestion -> loading -> answer with citation',
        (tester) async {
      final asker = _FakeAsker();
      await tester.pumpWidget(_host(SeasonQuestionScreen(
          asker: asker, cropSeasonId: 'season-1', seasonLabel: 'Vụ A')));
      await tester.tap(find.text('Vụ này còn thiếu dữ liệu gì?'));
      await tester.pump();
      expect(asker.calls.single, (
        'season-1',
        'Vụ này còn thiếu dữ liệu gì?',
        SeasonQuestionIntent.dataGap
      ));
      expect(find.text('Đang soạn câu trả lời…'), findsOneWidget);
      asker.pending.single.complete(SeasonQuestionAnswer.fromJson(
          _answerJson('season-1', status: 'insufficient_evidence')));
      await tester.pumpAndSettle();
      expect(find.text('Vụ chưa có dữ liệu thu hoạch.'), findsOneWidget);
      expect(find.textContaining('Hướng dẫn AWD'), findsOneWidget);
      expect(
          find.textContaining('Hệ thống soạn — không dùng AI'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('network failure shows retry; retry re-asks', (tester) async {
      final asker = _FakeAsker();
      await tester.pumpWidget(_host(SeasonQuestionScreen(
          asker: asker, cropSeasonId: 's', seasonLabel: 'Vụ A')));
      await tester.enterText(
          find.byKey(const Key('season-question-input')), 'Vụ này ra sao?');
      await tester.pump();
      await tester.ensureVisible(find.text('Gửi câu hỏi'));
      await tester.tap(find.text('Gửi câu hỏi'));
      await tester.pump();
      asker.pending.single.completeError(
          const SeasonQuestionException(SeasonQuestionFailure.offline));
      await tester.pumpAndSettle();
      expect(
          find.text(
              seasonQuestionFailureMessage(SeasonQuestionFailure.offline)),
          findsOneWidget);
      await tester.ensureVisible(find.text('Thử lại'));
      await tester.tap(find.text('Thử lại'));
      await tester.pump();
      expect(asker.calls, hasLength(2));
      expect(asker.calls.last.$2, 'Vụ này ra sao?');
    });

    testWidgets('non-retryable failure has no retry button', (tester) async {
      final asker = _FakeAsker();
      await tester.pumpWidget(_host(SeasonQuestionScreen(
          asker: asker, cropSeasonId: 's', seasonLabel: 'Vụ A')));
      await tester.tap(find.text('Vụ này đang thế nào?'));
      await tester.pump();
      asker.pending.single.completeError(
          const SeasonQuestionException(SeasonQuestionFailure.disabled));
      await tester.pumpAndSettle();
      expect(find.text('Thử lại'), findsNothing);
    });

    testWidgets('answer for another season is never shown', (tester) async {
      final asker = _FakeAsker();
      await tester.pumpWidget(_host(SeasonQuestionScreen(
          asker: asker, cropSeasonId: 'season-1', seasonLabel: 'Vụ A')));
      await tester.tap(find.text('Vụ này đang thế nào?'));
      await tester.pump();
      asker.pending.single
          .complete(SeasonQuestionAnswer.fromJson(_answerJson('season-OTHER')));
      await tester.pumpAndSettle();
      expect(find.text('Vụ đã ghi 3 hoạt động.'), findsNothing);
    });

    testWidgets('leaving the screen cancels the request', (tester) async {
      final asker = _FakeAsker();
      await tester.pumpWidget(_host(SeasonQuestionScreen(
          asker: asker, cropSeasonId: 's', seasonLabel: 'Vụ A')));
      await tester.tap(find.text('Vụ này đang thế nào?'));
      await tester.pump();
      await tester.pumpWidget(_host(const SizedBox()));
      expect(asker.cancels, 1);
    });

    testWidgets('account change drops the answer and closes the screen',
        (tester) async {
      final asker = _FakeAsker();
      final scope = ValueNotifier<String?>('user-a');
      await tester.pumpWidget(_host(Builder(
          builder: (context) => TextButton(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SeasonQuestionScreen(
                      asker: asker,
                      cropSeasonId: 's',
                      seasonLabel: 'Vụ A',
                      scope: scope,
                      scopeKey: () => scope.value))),
              child: const Text('open')))));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Vụ này đang thế nào?'));
      await tester.pump();
      asker.pending.single
          .complete(SeasonQuestionAnswer.fromJson(_answerJson('s')));
      await tester.pumpAndSettle();
      expect(find.text('Vụ đã ghi 3 hoạt động.'), findsOneWidget);
      scope.value = 'user-b';
      await tester.pumpAndSettle();
      expect(find.byType(SeasonQuestionScreen), findsNothing);
      expect(find.text('Vụ đã ghi 3 hoạt động.'), findsNothing);
    });

    for (final (w, h, scale) in [
      (320.0, 568.0, 1.0),
      (320.0, 568.0, 1.8),
      (430.0, 932.0, 1.3)
    ]) {
      testWidgets('no overflow at ${w}x$h text ${scale}x', (tester) async {
        tester.view.physicalSize = Size(w, h);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        final asker = _FakeAsker();
        await tester.pumpWidget(MaterialApp(
            theme: AgriCarbonTheme.light(),
            builder: (context, child) => MediaQuery(
                data: MediaQuery.of(context)
                    .copyWith(textScaler: TextScaler.linear(scale)),
                child: child!),
            home: SeasonQuestionScreen(
                asker: asker,
                cropSeasonId: 's',
                seasonLabel: 'Vụ Đông Xuân 2026')));
        await tester.ensureVisible(find.text('Vụ này đang thế nào?'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Vụ này đang thế nào?'));
        await tester.pump();
        asker.pending.single.complete(SeasonQuestionAnswer.fromJson(
            _answerJson('s', status: 'insufficient_evidence')));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }
  });

  group('UI preview entry', () {
    for (final page in preview.PreviewPage.values) {
      testWidgets('${page.name} renders with the preview label',
          (tester) async {
        tester.view.physicalSize = const Size(360, 780);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        await tester.pumpWidget(const preview.FlutterUiPreview());
        await tester.tap(find.byKey(const Key('preview-menu')));
        await tester.pumpAndSettle();
        await tester.tap(find.text(page.label).last);
        // The states page shows a spinner that never settles.
        await tester.pump(const Duration(milliseconds: 500));
        await tester.pump(const Duration(milliseconds: 500));
        expect(find.textContaining(preview.kPreviewDataLabel), findsWidgets);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('pricing -> choose PLUS -> selected-plan review',
        (tester) async {
      tester.view.physicalSize = const Size(360, 780);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(const preview.FlutterUiPreview());
      await tester.tap(find.byKey(const Key('preview-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.text(preview.PreviewPage.pricing.label).last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('preview-open-pricing')));
      await tester.pumpAndSettle();
      final buy = find.text('Mua ngay').first;
      await tester.ensureVisible(buy);
      await tester.pumpAndSettle();
      await tester.tap(buy);
      await tester.pumpAndSettle();
      expect(find.text('Gói dịch vụ đã chọn'), findsOneWidget);
      expect(find.textContaining('Chưa phát sinh thanh toán'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
