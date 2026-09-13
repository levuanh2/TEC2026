/// Bề mặt hẹp mà màn đăng nhập / quên mật khẩu cần — tách khỏi [AuthController]
/// để widget test có thể bơm bản giả mà không cần Supabase.
abstract interface class AuthActions {
  /// Đăng nhập bằng email + mật khẩu. Ném lỗi (thường là `AuthException`) khi
  /// thất bại; caller dịch bằng `authErrorMessage`.
  Future<void> signIn({required String email, required String password});

  /// Gửi email đặt lại mật khẩu (flow chuẩn Supabase). Không ném khi email
  /// không tồn tại — theo thiết kế chống dò tài khoản.
  Future<void> sendPasswordReset(String email);
}
