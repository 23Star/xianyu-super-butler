// 注册/改密场景的账号字段格式校验（前端提示层）。
// 规则与文案和后端 app/auth_validators.py 逐字一致：
// 前端让用户先看到原因，后端是防绕过 API 直调的最终防线。

const USERNAME_PATTERN = /^[A-Za-z0-9_-]{3,32}$/;
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PASSWORD_MAX_BYTES = 72;

export function validateUsername(username: string): [boolean, string] {
  if (!username) return [false, '用户名不能为空'];
  if (!USERNAME_PATTERN.test(username)) {
    return [false, '用户名需为 3-32 位字母、数字、下划线或连字符'];
  }
  return [true, ''];
}

export function validateEmail(email: string): [boolean, string] {
  if (!email) return [false, '邮箱不能为空'];
  if (email.length > 254) return [false, '邮箱地址过长'];
  if (!EMAIL_PATTERN.test(email)) return [false, '邮箱格式不正确'];
  return [true, ''];
}

export function validatePassword(password: string): [boolean, string] {
  if (!password) return [false, '密码不能为空'];
  if (password.length < 8) return [false, '密码至少 8 位，且需同时包含字母和数字'];
  if (password.length > 64) return [false, '密码最长 64 位'];
  if (new TextEncoder().encode(password).length > PASSWORD_MAX_BYTES) {
    return [false, '密码过长（超过 72 字节），请缩短后重试'];
  }
  const hasLetter = /[a-zA-Z]/.test(password);
  const hasDigit = /\d/.test(password);
  if (!hasLetter || !hasDigit) return [false, '密码至少 8 位，且需同时包含字母和数字'];
  return [true, ''];
}
