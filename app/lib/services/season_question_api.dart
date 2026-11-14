import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';

/// READ-tier intents only. `recommend` / `what_if` are deliberately absent:
/// they need Core V1 write authority and a configured AI provider, and this
/// local-QA screen must never reach a provider.
enum SeasonQuestionIntent {
  explain('explain', 'Giải thích vụ'),
  dataGap('data_gap', 'Dữ liệu còn thiếu'),
  evidence('evidence', 'Tài liệu tham khảo'),
  compare('compare', 'So sánh');

  const SeasonQuestionIntent(this.wire, this.label);
  final String wire;
  final String label;

  static SeasonQuestionIntent? fromWire(String? value) {
    for (final i in values) {
      if (i.wire == value) return i;
    }
    return null;
  }
}

class SeasonQuestionCitation {
  const SeasonQuestionCitation({
    required this.title,
    required this.sourceType,
    this.section,
    this.documentVersion,
  });
  final String title;
  final String sourceType;
  final String? section;
  final String? documentVersion;
}

class SeasonQuestionFact {
  const SeasonQuestionFact({required this.kind, this.value, this.unit});
  final String kind;
  final Object? value;
  final String? unit;
}

/// One server answer, as returned. The app computes nothing from it.
class SeasonQuestionAnswer {
  const SeasonQuestionAnswer({
    required this.status,
    required this.intent,
    required this.cropSeasonId,
    required this.systemComposed,
    this.answer,
    this.insufficientReason,
    this.limitations = const [],
    this.citations = const [],
    this.facts = const [],
  });

  /// `generated` | `insufficient_evidence` | `needs_clarification`.
  final String status;
  final String intent;
  final String cropSeasonId;
  final String? answer;
  final String? insufficientReason;
  final List<String> limitations;
  final List<SeasonQuestionCitation> citations;
  final List<SeasonQuestionFact> facts;

  /// `provenance.answer_source == system_composed` (no model was called).
  final bool systemComposed;

  bool get insufficient => status != 'generated';

  static SeasonQuestionAnswer fromJson(Map<String, dynamic> json) {
    List<Map<String, dynamic>> maps(Object? v) => v is List
        ? v.whereType<Map<String, dynamic>>().toList()
        : const <Map<String, dynamic>>[];
    final provenance = json['provenance'];
    return SeasonQuestionAnswer(
      status: (json['status'] as String?) ?? 'insufficient_evidence',
      intent: (json['intent'] as String?) ?? '',
      cropSeasonId: (json['crop_season_id'] as String?) ?? '',
      answer: json['answer'] as String?,
      insufficientReason: json['insufficient_reason'] as String?,
      limitations: (json['limitations'] is List)
          ? (json['limitations'] as List).whereType<String>().toList()
          : const [],
      citations: [
        for (final c in maps(json['citations']))
          SeasonQuestionCitation(
            title: (c['title'] as String?) ?? '',
            sourceType: (c['source_type'] as String?) ?? '',
            section: c['section'] as String?,
            documentVersion: c['document_version'] as String?,
          ),
      ],
      facts: [
        for (final f in maps(json['trusted_facts']))
          SeasonQuestionFact(
            kind: (f['kind'] as String?) ?? '',
            value: f['value'],
            unit: f['unit'] as String?,
          ),
      ],
      systemComposed: provenance is! Map ||
          provenance['answer_source'] != 'model_generated',
    );
  }
}

enum SeasonQuestionFailure {
  offline,
  timeout,
  unauthenticated,
  notFound,
  invalid,
  disabled,
  generationUnavailable,
  citationBlocked,
  quota,
  server,
}

class SeasonQuestionException implements Exception {
  const SeasonQuestionException(this.failure, {this.statusCode});
  final SeasonQuestionFailure failure;
  final int? statusCode;

  /// Retry makes sense only for transient failures.
  bool get retryable => switch (failure) {
        SeasonQuestionFailure.offline ||
        SeasonQuestionFailure.timeout ||
        SeasonQuestionFailure.citationBlocked ||
        SeasonQuestionFailure.server =>
          true,
        _ => false,
      };

  @override
  String toString() => 'SeasonQuestionException($failure, $statusCode)';
}

/// The request was cancelled by the caller (screen closed / new question).
class SeasonQuestionCancelled implements Exception {
  const SeasonQuestionCancelled();
}

/// A cancellable in-flight question.
class SeasonQuestionRequest {
  SeasonQuestionRequest(this.future, this._cancel);
  final Future<SeasonQuestionAnswer> future;
  final void Function() _cancel;
  void cancel() => _cancel();
}

abstract class SeasonQuestionAsker {
  SeasonQuestionRequest ask(
    String cropSeasonId, {
    required String question,
    required SeasonQuestionIntent intent,
  });
}

/// `POST /v1/crop-seasons/{id}/questions` (backend/api.py). Scope comes from
/// the JWT only; the body carries nothing but the question and intent.
class SeasonQuestionApi implements SeasonQuestionAsker {
  SeasonQuestionApi(
    this._tokenProvider, {
    http.Client Function()? clientFactory,
    String? baseUrl,
    this.timeout = const Duration(seconds: 45),
  })  : _clientFactory = clientFactory ?? http.Client.new,
        _baseUrl = baseUrl ?? AppConfig.backendBaseUrl;

  final String? Function() _tokenProvider;
  final http.Client Function() _clientFactory;
  final String _baseUrl;
  final Duration timeout;

  @override
  SeasonQuestionRequest ask(
    String cropSeasonId, {
    required String question,
    required SeasonQuestionIntent intent,
  }) {
    // One client per request: closing it aborts the socket, which is how the
    // screen cancels a question when it is left.
    final client = _clientFactory();
    var cancelled = false;
    final completer = Completer<SeasonQuestionAnswer>();
    void settle(Object error) {
      if (!completer.isCompleted) completer.completeError(error);
    }

    () async {
      final token = _tokenProvider();
      if (token == null) {
        settle(const SeasonQuestionException(
            SeasonQuestionFailure.unauthenticated));
        return;
      }
      final uri = Uri.parse(
          '$_baseUrl/v1/crop-seasons/${Uri.encodeComponent(cropSeasonId)}/questions');
      try {
        final response = await client
            .post(uri,
                headers: {
                  'Authorization': 'Bearer $token',
                  'Accept': 'application/json',
                  'Content-Type': 'application/json',
                },
                body: jsonEncode({'question': question, 'intent': intent.wire}))
            .timeout(timeout);
        if (cancelled) return settle(const SeasonQuestionCancelled());
        final decoded = response.bodyBytes.isEmpty
            ? null
            : jsonDecode(utf8.decode(response.bodyBytes));
        final body =
            decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
        if (response.statusCode >= 200 && response.statusCode < 300) {
          if (!completer.isCompleted) {
            completer.complete(SeasonQuestionAnswer.fromJson(body));
          }
          return;
        }
        settle(SeasonQuestionException(_failureFor(response.statusCode, body),
            statusCode: response.statusCode));
      } on TimeoutException {
        settle(cancelled
            ? const SeasonQuestionCancelled()
            : const SeasonQuestionException(SeasonQuestionFailure.timeout));
      } on FormatException {
        settle(cancelled
            ? const SeasonQuestionCancelled()
            : const SeasonQuestionException(SeasonQuestionFailure.server));
      } catch (_) {
        // Socket/client errors: never surface their text (may contain URLs).
        settle(cancelled
            ? const SeasonQuestionCancelled()
            : const SeasonQuestionException(SeasonQuestionFailure.offline));
      } finally {
        client.close();
      }
    }();

    return SeasonQuestionRequest(completer.future, () {
      if (cancelled) return;
      cancelled = true;
      client.close();
      settle(const SeasonQuestionCancelled());
    });
  }

  static SeasonQuestionFailure _failureFor(
      int status, Map<String, dynamic> body) {
    final detail = body['detail'];
    String? code;
    if (detail is Map) {
      final error = detail['error'];
      if (error is Map) code = error['code'] as String?;
      if (error is String) code = error;
    }
    if (code == 'backend_not_configured') return SeasonQuestionFailure.disabled;
    if (code == 'generation_unavailable') {
      return SeasonQuestionFailure.generationUnavailable;
    }
    return switch (status) {
      401 => SeasonQuestionFailure.unauthenticated,
      403 || 404 => SeasonQuestionFailure.notFound,
      422 => SeasonQuestionFailure.invalid,
      429 => SeasonQuestionFailure.quota,
      502 => SeasonQuestionFailure.citationBlocked,
      // 503 retrieval_unavailable is transient; backend_not_configured is
      // handled above by its code.
      _ => SeasonQuestionFailure.server,
    };
  }
}
