/**
 * 飞书机器人加签工具
 * 使用 Web Crypto API 计算 HMAC-SHA256
 * 签名字符串 = timestamp + "\n" + secret
 */

export interface FeishuSignResult {
  timestamp: string;
  sign: string;
}

function base64FromBytes(bytes: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * 计算飞书加签签名
 * 签名字符串 = timestamp + "\n" + secret
 * 使用 HMAC-SHA256 算法，secret 作为 key
 * 结果 base64 encode 后 URL encode
 */
export async function computeFeishuSign(secret: string): Promise<FeishuSignResult> {
  if (!crypto?.subtle) {
    throw new Error('当前环境不支持 Web Crypto API，无法计算飞书加签');
  }

  const timestamp = Date.now().toString();
  const stringToSign = `${timestamp}\n${secret}`;

  const encoder = new TextEncoder();
  const keyData = encoder.encode(secret);
  const messageData = encoder.encode(stringToSign);

  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    keyData,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );

  const signature = await crypto.subtle.sign('HMAC', cryptoKey, messageData);
  const bytes = new Uint8Array(signature);
  const base64 = base64FromBytes(bytes);
  const sign = encodeURIComponent(base64);

  return { timestamp, sign };
}

/**
 * 将签名参数追加到飞书 Webhook URL
 * 如果 secret 为空则原样返回 URL
 */
export async function appendFeishuSign(url: string, secret: string): Promise<string> {
  if (!secret.trim()) return url;
  const { timestamp, sign } = await computeFeishuSign(secret.trim());
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}timestamp=${timestamp}&sign=${sign}`;
}
