"""shenwei-mockkit：模拟 ERP / SCRM 共用的内核。

两套模拟系统各管各的业务对象，但下面这些"像不像工业级"的东西是一样的，所以抽出来只写一次：
  身份与租户      X-Api-Key 定租户、X-Actor 写必带、跨租户 404 并记违规、X-Admin-Token 管管理口
  问题详情错误    RFC 9457 application/problem+json，机器码放 code，请求 ID 放 instance
  请求 ID         X-Request-Id 可带可不带，没有就生成 ULID，响应原样带回，账本里能查
  幂等            Idempotency-Key 只对 POST；同键同体重放原响应 + Idempotent-Replay；同键不同体 409；同键在途 409
  乐观锁          ETag / If-Match，不匹配 412
  故障注入        timeout / slow / error / response_lost / rate_limit / malformed，按 METHOD /path 通配，可限租户
  虚拟时钟        只能向前；所有"今天"都从它算
  事件与 webhook  统一信封、HMAC-SHA256 签名、至少一次、可重复可乱序、失败重试、按 sequence 回拉
  游标分页        {data, has_more, next_cursor}
  场景装载        /_admin/scenario 的 upsert 与故障 / 事件登记
"""
from .store import Store, TZ, iso, parse, today_of          # noqa: F401
from .problems import Problem, install_error_handlers        # noqa: F401
from .identity import Identity, Caller                       # noqa: F401
from .middleware import install_middleware, note             # noqa: F401
from .idempotency import Idempotency                         # noqa: F401
from .paging import paginate                                 # noqa: F401
from .etag import etag_of, check_if_match                    # noqa: F401
from .webhooks import Events, sign                           # noqa: F401
from .ids import ulid                                        # noqa: F401
# revision: 04728 03F07
