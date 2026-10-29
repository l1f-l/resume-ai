export type DiffPart = { text: string; type: "same" | "add" | "del" };

/**
 * 字符级 LCS diff：中文没有空格分词，字符级最直观。
 * 长度做了上限保护，避免长段文本把主线程卡住。
 */
export function diffChars(before: string, after: string): DiffPart[] {
  const a = [...(before || "")].slice(0, 400);
  const b = [...(after || "")].slice(0, 400);
  const n = a.length;
  const m = b.length;

  const dp: Int32Array[] = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const parts: DiffPart[] = [];
  const push = (text: string, type: DiffPart["type"]) => {
    if (!text) return;
    const last = parts[parts.length - 1];
    if (last && last.type === type) last.text += text;
    else parts.push({ text, type });
  };

  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push(a[i], "same");
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push(a[i], "del");
      i++;
    } else {
      push(b[j], "add");
      j++;
    }
  }
  while (i < n) push(a[i++], "del");
  while (j < m) push(b[j++], "add");
  return parts;
}

export function changedStats(before: string, after: string): { added: number; removed: number } {
  const parts = diffChars(before, after);
  let added = 0;
  let removed = 0;
  for (const p of parts) {
    if (p.type === "add") added += [...p.text].length;
    if (p.type === "del") removed += [...p.text].length;
  }
  return { added, removed };
}
