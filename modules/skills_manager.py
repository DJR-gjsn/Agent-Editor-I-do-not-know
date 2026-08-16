"""
Skills Manager 技能管理器模块
集中管理所有技能组件的 System Prompt，合并后统一注入 LLM
技能组件只能连接到本模块，不能直连 LLM 或其他模块
"""

from flask import jsonify, request

from . import tool_registry

# 技能 ID 列表（与 mcp_skills.py 中 SKILLS 的 key 对应）
MANAGED_SKILL_IDS = [
    "document",
    "frontend-design",
    "ui-ux-pro-max",
    "find-skills",
    "skill-creator",
    "superpowers",
    "pua",
]


def register_routes(app, http_session=None):
    """注册技能管理器相关路由"""

    @app.route("/api/skills-manager/combine", methods=["POST"])
    def skills_manager_combine():
        """
        接收技能 ID 列表，返回合并后的 System Prompt
        用于 skills_manager 组件前端调用
        """
        data = request.get_json(force=True)
        skill_ids = data.get("skill_ids", [])

        from .mcp_skills import SKILLS

        combined = []
        for sid in skill_ids:
            s = SKILLS.get(sid)
            if s:
                combined.append(f"## {s['name']}\n{s['system_prompt']}")

        if not combined:
            return jsonify({"combined_prompt": "", "skill_count": 0})

        separator = "\n\n---\n\n"
        return jsonify({
            "combined_prompt": separator.join(combined),
            "skill_count": len(combined),
            "skill_names": [SKILLS[sid]["name"] for sid in skill_ids if sid in SKILLS],
        })

    @app.route("/api/skills-manager/status")
    def skills_manager_status():
        """返回技能管理器状态：可用技能列表"""
        from .mcp_skills import SKILLS

        return jsonify({
            "managed_skills": [
                {
                    "id": sid,
                    "name": SKILLS[sid]["name"],
                    "description": SKILLS[sid]["description"],
                    "category": SKILLS[sid]["category"],
                }
                for sid in MANAGED_SKILL_IDS if sid in SKILLS
            ],
            "total": len(MANAGED_SKILL_IDS),
        })
