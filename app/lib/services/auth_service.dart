import 'package:supabase_flutter/supabase_flutter.dart';

import '../config.dart';

/// Bọc Supabase Auth. Token do package tự lưu an toàn (flutter_secure_storage ở
/// dưới) — app không tự chạm vào chuỗi JWT, không lưu tay ở đâu khác.
///
/// KHÔNG có SUPABASE_SERVICE_ROLE_KEY trong app — chỉ publishable key
/// (AppConfig.supabasePublishableKey). RLS vẫn là ranh giới quyền thật, giống
/// hệt web-dashboard/src/utils/supabase.ts.
class AuthService {
  static Future<void> init() => Supabase.initialize(
        url: AppConfig.supabaseUrl,
        anonKey: AppConfig.supabasePublishableKey,
      );

  SupabaseClient get client => Supabase.instance.client;

  Session? get currentSession => client.auth.currentSession;
  bool get isSignedIn => currentSession != null;
  String? get accessToken => currentSession?.accessToken;
  String? get userId => currentSession?.user.id;

  Stream<AuthState> get onAuthStateChange => client.auth.onAuthStateChange;

  Future<void> signIn({required String email, required String password}) async {
    await client.auth.signInWithPassword(email: email, password: password);
  }

  Future<void> signOut() => client.auth.signOut();
}
