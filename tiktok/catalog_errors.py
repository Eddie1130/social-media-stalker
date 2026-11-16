"""Stable classifications without retaining private exception text."""
from dataclasses import dataclass
import json,re
@dataclass(frozen=True)
class Failure:
    category: str
    safe_code: str
    retryable: bool

def classify_failure(error,response_meta=None):
    text=str(error)
    if 'CAPTCHA' in text:return Failure('captcha','TIKTOK_CAPTCHA_REQUIRED',False)
    if any(x in text for x in ('LOGIN','COOKIE','SESSION_INVALID','AUTH')):return Failure('auth','TIKTOK_AUTH_REQUIRED',False)
    if (response_meta or {}).get('status')==429 or 'RATE_LIMIT' in text:return Failure('rate_limit','TIKTOK_RATE_LIMITED',False)
    if 'EMPTY_RESPONSE' in text:return Failure('empty_response','TIKTOK_EMPTY_RESPONSE',True)
    if 'BROWSER_TRANSPORT' in text or type(error).__name__=='TargetClosedError':return Failure('transport','TIKTOK_BROWSER_TRANSPORT_FAILED',True)
    if isinstance(error,json.JSONDecodeError):return Failure('parse_contract','TIKTOK_RESPONSE_INVALID',False)
    if isinstance(error,OSError) and getattr(error,'errno',None) in (13,28,30):return Failure('storage','TIKTOK_STORAGE_FAILED',False)
    if type(error).__name__=='TimeoutError' or 'TIMEOUT' in text or 'net::ERR_' in text:return Failure('network','TIKTOK_NETWORK_FAILED',False)
    return Failure('parse_contract',text if re.fullmatch(r'TIKTOK_[A-Z0-9_]{1,64}',text) else 'TIKTOK_PROVIDER_FAILED',False)
