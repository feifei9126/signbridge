#!/usr/bin/env python3
"""Create a static, local overview of the three evidence-only experiments."""
import argparse
import hashlib
import html
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def pct(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def run(semantic_path, motion_path, candidate_path, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Choose a new dashboard directory")
    semantic = read(semantic_path)
    motion = read(motion_path)
    candidates = read(candidate_path)
    base = semantic["baseline"]["metrics"]
    scope = semantic["scope_experiment"]["metrics"]
    groups = semantic["scope_experiment"]["by_partition"]
    clean_base = semantic["leakage_excluded_baseline"]
    clean_scope = semantic["leakage_excluded_scope_experiment"]
    clean_groups = clean_scope["by_partition"]
    summary = motion["summary"]
    candidate_rows = candidates["candidates"]
    bodies = []
    for row in motion["records"]:
        baseline, adaptive = row["profiles"]["existing"], row["profiles"]["adaptive"]
        bodies.append(
            "<tr>"
            f"<td>{html.escape(row['text'])}</td><td>{html.escape(row['id'])}</td>"
            f"<td>{baseline['metrics']['wristMidpointP95Cm']:.2f} cm</td>"
            f"<td>{adaptive['metrics']['wristMidpointP95Cm']:.2f} cm</td>"
            f"<td>{adaptive['minimumWristRangeRetention'] * 100:.1f}%</td>"
            f"<td>{adaptive['fingerEndJointDisplacementP95Cm']:.2f} cm</td>"
            f"<td>{'研究门槛通过' if row['adaptivePassesNumericComparison'] else '未通过'}</td></tr>"
        )
    candidate_labels = "、".join(html.escape(row["proposed_text"]) for row in candidate_rows)
    output.mkdir(parents=True)
    report = {
        "schema": "signbridge-existing-resource-optimization-summary-v1",
        "semantic_fixture_sha256": semantic["fixture_sha256"],
        "semantic_group_overlap_with_old_training": len(semantic["old_training_text_overlap"]),
        "baseline_metrics": base,
        "scope_experiment_metrics": scope,
        "scope_partition_metrics": groups,
        "leakage_excluded_metrics": {"baseline": clean_base["metrics"], "scope": clean_scope["metrics"]},
        "leakage_excluded_partition_metrics": clean_groups,
        "motion_summary": summary,
        "motion_record_count": len(motion["records"]),
        "unit_candidate_count": len(candidate_rows),
        "unit_candidate_decoded_frames": sum(row["decode"]["frames"] for row in candidate_rows),
        "verified_word_units": candidates["verified_word_units"],
        "model_training_ready": False,
        "human_approved": False,
    }
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    page = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SignBridge · 现有资源优化证据</title>
<style>
:root{{font:15px/1.55 system-ui,sans-serif;color:#18342e;background:#f4f6f2}}
*{{box-sizing:border-box}}body{{max-width:1240px;margin:28px auto;padding:0 18px}}
h1{{font-size:28px}}h2{{margin:0 0 10px;font-size:20px}}p{{color:#566a61}}
section{{border-top:1px solid #b9c9c0;padding:22px 0}}.metrics{{display:flex;flex-wrap:wrap;gap:12px}}
.metric{{padding:12px 16px;background:white;border:1px solid #c7d3cc;border-radius:6px;min-width:170px}}
.metric strong{{display:block;font-size:22px}}table{{width:100%;border-collapse:collapse;background:white;font-size:13px}}
th,td{{border-bottom:1px solid #d5dfd9;padding:8px;text-align:left;vertical-align:top}}th{{position:sticky;top:0;background:#e8eeea}}
.table{{max-height:620px;overflow:auto;border:1px solid #c7d3cc}}a{{color:#175e50}}.warning{{border-left:4px solid #a85b26;padding:10px 14px;background:#fff3e8}}
.comparison{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}figure{{margin:0;background:white;border:1px solid #c7d3cc;padding:8px}}figure img{{display:block;width:100%;height:auto}}figcaption{{font-size:13px;padding:6px}}@media(max-width:700px){{.comparison{{grid-template-columns:1fr}}}}
</style>
<h1>基于现有资源的优化对照</h1>
<p>仅使用本机现有文本模型、六批动作、教学参考和 Godette 骨架；未训练、未修改原始轨迹或权重。</p>
<section><h2>中文作用域对照（冻结76例）</h2><div class="metrics">
<div class="metric"><span>排除旧训练文本后的基线覆盖</span><strong>{pct(clean_base['metrics']['supported_coverage'])}</strong></div>
<div class="metric"><span>排除重叠后的实验覆盖</span><strong>{pct(clean_scope['metrics']['supported_coverage'])}</strong></div>
<div class="metric"><span>结构留出覆盖（排重叠后）</span><strong>{pct(clean_groups['structure_holdout']['supported_coverage'])}</strong></div>
<div class="metric"><span>实验选择性正确率</span><strong>{pct(clean_scope['metrics']['selective_accuracy'])}</strong></div>
<div class="metric"><span>错误接受率</span><strong>{pct(clean_scope['metrics']['false_accept_rate'])}</strong></div>
<div class="metric"><span>已明确排除的训练重叠</span><strong>{len(semantic['old_training_text_overlap'])}例</strong></div>
</div><p>合成工程测试，不是自然中文总体准确率，更不是中国手语准确率。未训练，基线默认不变。对照详情：<a href="../semantic-contrast-v4/report.json">JSON</a></p>
<p class="warning">作用域实验复用冻结标签器，只增加有限结构约束。超出已列结构仍须拒答；不能把 76 例满分宣传为 CSL 能力。</p></section>
<section><h2>动作稳定性（{summary['clips']}段）</h2><div class="metrics">
<div class="metric"><span>现有腕部残差 P95 均值</span><strong>{summary['existingWristMidpointP95MeanCm']:.2f} cm</strong></div>
<div class="metric"><span>实验腕部残差 P95 均值</span><strong>{summary['adaptiveWristMidpointP95MeanCm']:.2f} cm</strong></div>
<div class="metric"><span>实验最小动作范围保留</span><strong>{summary['adaptiveMinimumRangeRetention'] * 100:.1f}%</strong></div>
<div class="metric"><span>共同门槛通过</span><strong>{summary['numericComparisonPass']}/{summary['clips']}</strong></div>
<div class="metric"><span>热缓存查找均值</span><strong>{summary['meanWarmLookupMs']:.3f} ms</strong></div>
</div><p>腕部中点残差是高频稳定代理；动作范围、手指末端骨骼原点位移和近手间距变化用于防止过度平滑。它们不是皮肤接触测量或 CSL 正确率。新实验没有片段通过联合数值门槛，因此不晋级默认预览。</p>
<p>同一动作暂停时间点的实际角色预览截图。画面比较不等于语义或手型审批。</p><div class="comparison"><figure><a href="../browser-feature-v3/sample-existing-profile.png"><img loading="lazy" src="../browser-feature-v3/sample-existing-profile.png" alt="现有显示配置的人物动作"></a><figcaption>现有显示配置</figcaption></figure><figure><a href="../browser-feature-v3/sample-isolated-spike-experiment.png"><img loading="lazy" src="../browser-feature-v3/sample-isolated-spike-experiment.png" alt="孤立尖峰实验的人物动作"></a><figcaption>孤立尖峰研究对照</figcaption></figure></div>
<div class="table"><table><thead><tr><th>文字</th><th>ID</th><th>现有腕部 P95</th><th>实验腕部 P95</th><th>实验范围保留</th><th>手指骨端位移 P95</th><th>决策</th></tr></thead><tbody>{''.join(bodies)}</tbody></table></div>
<p>完整逐片结果：<a href="../motion-comparison-v4/report.json">JSON</a>。原参数文件未写入，默认与恢复显示仍保持。</p></section>
<section><h2>旧教学资料候选（{len(candidate_rows)}项）</h2>
<p>复核：{candidate_labels}</p><p>原片摘要重验并完整解码 {report['unit_candidate_decoded_frames']} 帧；逐项保留既有粗窗口、解释笔记、缺失观测帧、观测活动区间建议和原视频联系表。</p>
<p class="warning">已核准词单元：0。活动区间只是2D观测峰值提示；源视频时间不是原始精确 PTS。镜像、解剖侧别、手语者、词界和语义仍未知。完整逐项原片／联系表：<a href="../unit-candidates-final/index.html">打开候选复核页</a>。</p></section>
<section><h2>有限表达计划</h2><p>作用域服务对“我今天去学校”等受限结构输出角色、事件树与组成候选；只有文字与已有证据完全匹配时显示证据，否则列为缺口。所有计划为 <code>review_required</code>，不生成播放项。候选不代表获批单元或 CSL 语序。</p><p>服务开关：<code>--scope-experiment --unit-candidates local-data/existing-resources-optimization-20261019-v1/unit-candidates-final/candidates.json</code></p></section>
<footer><p>人工批准、训练就绪与模型训练就绪均为 false。所有改进结果与原证据隔离保存。</p></footer></html>"""
    (output / "index.html").write_text(page)
    manifest = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            manifest.append(
                hashlib.sha256(path.read_bytes()).hexdigest()
                + "  "
                + str(path.relative_to(output))
            )
    (output / "SHA256SUMS").write_text("\n".join(manifest) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["semantic", "motion", "candidates", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.semantic, args.motion, args.candidates, args.output)
