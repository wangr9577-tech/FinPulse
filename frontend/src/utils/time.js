// 前端「今日」口径：过去 24 小时 (从当前时间回溯)，而非自然日历日。
// 与后端 mongodb.py 的 _is_within_past_hours (TODAY_WINDOW_HOURS=24) 保持一致。
export function isToday(t, hours = 24) {
  if (!t) return false
  const ts = new Date(t).getTime()
  if (Number.isNaN(ts)) return false
  return Date.now() - ts < hours * 3600 * 1000
}
