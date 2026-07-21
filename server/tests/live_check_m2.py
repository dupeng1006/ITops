# -*- coding: utf-8 -*-
"""M2 活服务集成验证（8019 源码态）：建任务→基线统计→热生效→下载"""
import json
import sys
import time
from pathlib import Path

import httpx

import os
BASE = os.environ.get("M2_LIVE_BASE", "http://127.0.0.1:8019")
SAMPLE = Path("tests/golden/m2/samples")
EXPECT = Path("tests/golden/m2/expected/expected_stats.json")

failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def m2_files():
    files = []
    for name in ("新综合信息查询_基金证券-6301.xlsx", "新综合信息查询_基金证券-6302.xlsx"):
        files.append(("system_files", (name, (SAMPLE / name).read_bytes(),
                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")))
    for name in ("证券投资基金估值表_6301-20260720.xlsx", "证券投资基金估值表_6302-20260720.xlsx"):
        files.append(("valuation_files", (name, (SAMPLE / name).read_bytes(),
                                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")))
    return files


def poll(client, token, job_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"{BASE}/api/recon/jobs/{job_id}",
                       headers={"Authorization": f"Bearer {token}"})
        j = r.json()
        if j["status"] in ("success", "failed"):
            return j
        time.sleep(0.5)
    raise TimeoutError(job_id)


def main():
    expected = json.loads(EXPECT.read_text(encoding="utf-8"))
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "Admin@123"})
        check("活服务 admin 登录 200", r.status_code == 200, r.text)
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        if r.json().get("must_change_password"):
            r2 = c.post(f"{BASE}/api/auth/change-password",
                        json={"old_password": "Admin@123", "new_password": "Admin@2026New"}, headers=h)
            check("活服务改密 200", r2.status_code == 200, r2.text)

        r = c.get(f"{BASE}/api/admin/system/subject-price-rules", headers=h)
        seeds = {x["subject_prefix"]: x["price_field"] for x in r.json()}
        check("活服务种子规则 1101→市价/1501→单位成本",
              seeds.get("1101") == "市价" and seeds.get("1501") == "单位成本", str(seeds))

        r = c.post(f"{BASE}/api/recon/m2/jobs", files=m2_files(), headers=h)
        check("活服务创建 M2 任务 200", r.status_code == 200, r.text)
        job1 = poll(c, token, r.json()["job_id"])
        check("活服务基线任务成功", job1["status"] == "success", str(job1.get("error")))
        check("活服务基线统计==黄金基线", job1["stats"] == expected, str(job1["stats"]))

        r = c.get(f"{BASE}/api/recon/jobs/{job1['job_id']}/download",
                  params={"product": "6301"}, headers=h)
        check("活服务下载 6301 报告 200(PK)", r.status_code == 200 and r.content[:2] == b"PK",
              f"status={r.status_code}")

        r = c.post(f"{BASE}/api/admin/system/subject-price-rules",
                   json={"subject_prefix": "1102", "price_field": "市价",
                         "description": "其他投资", "sort_order": 3}, headers=h)
        check("活服务新增 1102 规则 200", r.status_code == 200, r.text)
        rid = r.json()["id"]

        r = c.post(f"{BASE}/api/recon/m2/jobs", files=m2_files(), headers=h)
        job2 = poll(c, token, r.json()["job_id"])
        hot = (job2["stats"] or {}).get("products", {}).get("6301", {})
        check("活服务热生效 6301=8/2/2/4",
              hot == {"总记录": 8, "一致": 2, "差异": 2, "单边": 4}, str(hot))

        r = c.delete(f"{BASE}/api/admin/system/subject-price-rules/{rid}", headers=h)
        check("活服务删除 1102 规则 200", r.status_code == 200, r.text)
        r = c.post(f"{BASE}/api/recon/m2/jobs", files=m2_files(), headers=h)
        job3 = poll(c, token, r.json()["job_id"])
        check("活服务删除后回到基线", job3["stats"] == expected, str(job3["stats"]))

        r = c.get(f"{BASE}/recon/m2", headers=h)
        check("SPA 路由 /recon/m2 可访问(200 html)",
              r.status_code == 200 and b"html" in r.content[:200].lower(), f"status={r.status_code}")
        r = c.get(f"{BASE}/system/config", headers=h)
        check("SPA 路由 /system/config 可访问(200 html)",
              r.status_code == 200 and b"html" in r.content[:200].lower(), f"status={r.status_code}")

    print("=" * 60)
    if failures:
        print(f"活服务集成验证失败 {len(failures)} 项")
        for f_ in failures:
            print(f"  - {f_}")
        return 1
    print("活服务集成验证全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
