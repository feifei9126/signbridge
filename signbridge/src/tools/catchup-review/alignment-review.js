const rows = (await (await fetch("cases.jsonl")).text())
  .split(/\n/)
  .filter(Boolean)
  .map(JSON.parse);
const summary = await (await fetch("summary.json")).json();
const list = document.querySelector("#list");
const filter = document.querySelector("#filter");
const search = document.querySelector("#search");
let page = 0;
const pageSize = 16;
document.querySelector("#summary").textContent =
  `${summary.cases} 帧 · 组合门槛 ${summary.combined_gate_passed} 通过 / ${summary.combined_gate_failed} 未通过 · MANO 候选 ${summary.mano_alternatives} · 所有候选门槛通过 ${summary.all_candidates_gate_passed} · 未训练`;

function render() {
  const query = search.value.trim().toLocaleLowerCase();
  const found = rows.filter((row) => {
    const gateMatch =
      filter.value === "all" ||
      (filter.value === "pass" && row.combined_projection_gate_passed) ||
      (filter.value === "fail" && !row.combined_projection_gate_passed) ||
      (filter.value === "noguess" && row.candidate_alternatives === 0);
    return gateMatch && JSON.stringify(row).toLocaleLowerCase().includes(query);
  });
  const pages = Math.max(1, Math.ceil(found.length / pageSize));
  page = Math.max(0, Math.min(page, pages - 1));
  document.querySelector("#count").textContent =
    `${found.length} 项 · 第 ${page + 1}/${pages} 页`;
  list.replaceChildren();
  for (const row of found.slice(page * pageSize, (page + 1) * pageSize)) {
    const card = document.createElement("section");
    const heading = document.createElement("h2");
    heading.textContent = `${row.label} · ${row.combined_projection_gate_passed ? "组合投影门槛通过" : "组合投影门槛未通过"}`;
    const details = document.createElement("p");
    details.textContent = `${row.case_id} · ${row.source_id} · ${row.source_seconds_nominal}s · MANO候选 ${row.candidate_alternatives} · 失败侧 ${row.failed_selected_sides.join(",") || "无"}`;
    card.append(heading, details);
    if (row.image) {
      const image = document.createElement("img");
      image.loading = "lazy";
      image.src = row.image;
      image.alt = `${row.label} 原片、SMPL-X基线、未批准的对齐候选`;
      card.append(image);
    }
    list.append(card);
  }
  document.querySelector("#previous").disabled = page === 0;
  document.querySelector("#next").disabled = page + 1 >= pages;
}

for (const control of [filter, search])
  control.addEventListener("input", () => {
    page = 0;
    render();
  });
document.querySelector("#previous").addEventListener("click", () => {
  page--;
  render();
});
document.querySelector("#next").addEventListener("click", () => {
  page++;
  render();
});
render();
