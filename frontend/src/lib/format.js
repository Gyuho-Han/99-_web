const nf = new Intl.NumberFormat("ko-KR");
const usd = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/* 현재 시장의 통화. store 가 시장을 바꿀 때 같이 갱신한다.
   금액 포맷터가 전부 이 값을 보므로 화면 코드는 통화를 신경 쓰지 않아도 된다. */
let currency = "KRW";
export function setCurrency(c) {
  currency = c === "USD" ? "USD" : "KRW";
}
export function getCurrency() {
  return currency;
}
export const isUSD = () => currency === "USD";

export const won = (v) =>
  currency === "USD" ? `$${usd.format(v ?? 0)}` : `${nf.format(Math.round(v ?? 0))}원`;

export const wonShort = (v) => {
  if (currency === "USD") {
    const n = Math.abs(v ?? 0);
    if (n >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
    return `$${usd.format(v ?? 0)}`;
  }
  const n = Math.abs(v ?? 0);
  if (n >= 100_000_000) return `${(v / 100_000_000).toFixed(2)}억`;
  if (n >= 10_000) return `${(v / 10_000).toFixed(0)}만`;
  return nf.format(Math.round(v ?? 0));
};
export const num = (v, d = 0) =>
  nf.format(Number((v ?? 0).toFixed(d)));

export const signed = (v, d = 2, suffix = "%") =>
  `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v ?? 0).toFixed(d)}${suffix}`;

export const signedWon = (v) => {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const n = Math.abs(v ?? 0);
  return currency === "USD" ? `${sign}$${usd.format(n)}` : `${sign}${nf.format(Math.round(n))}`;
};

/** 가격 표기: 원화는 정수, 달러는 센트까지. */
export const price = (v) =>
  currency === "USD" ? `$${usd.format(v ?? 0)}` : nf.format(Math.round(v ?? 0));

/** 국내 관례: 상승 적색 / 하락 청색 */
export const toneOf = (v) => (v > 0 ? "up" : v < 0 ? "down" : "flat");
export const toneClass = (v) =>
  v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted";

export const dateShort = (iso) => {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${String(d.getDate()).padStart(2, "0")}`;
};
export const dateTime = (iso) => {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export const ACTION_LABEL = { buy: "매수", hold: "관망", sell: "매도" };
export const STATUS_LABEL = {
  pending: "접수",
  filled: "체결",
  partial: "부분체결",
  canceled: "취소",
  rejected: "거부",
};
