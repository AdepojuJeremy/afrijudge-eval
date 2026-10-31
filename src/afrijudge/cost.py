"""Conditional cost scenarios; token assumptions are not guaranteed upper bounds."""

from afrijudge.pipeline import plan


def estimate(
    config: dict, model_lock: dict, generation_input: int = 500, judge_input: int = 650
) -> dict:
    for value in (generation_input, judge_input):
        if type(value) is not int or value < 0:
            raise ValueError("Assumed input token counts must be nonnegative integers")
    counts = plan(config)
    base_per_generator = counts["generation_calls"] // len(config["generators"])
    judge_per_model = counts["maximum_judge_calls"] // len(config["judges"])
    # Mirrors the deterministic alternating assignment in pipeline.run.
    foil_per_model = {
        config["generators"][0]: ((counts["foil_calls"] // 2 + 1) // 2) * 2,
        config["generators"][1]: (counts["foil_calls"] // 4) * 2,
    }
    scenarios = []
    for name, gin, gout, jin, jout in (
        (
            "illustrative_usage",
            generation_input,
            min(350, config["generation_max_tokens"]),
            judge_input,
            min(150, config["judge_max_tokens"]),
        ),
        (
            "full_output_caps",
            generation_input,
            config["generation_max_tokens"],
            judge_input,
            config["judge_max_tokens"],
        ),
        (
            "longer_inputs_full_output_caps",
            max(generation_input, 1000),
            config["generation_max_tokens"],
            max(judge_input, 1500),
            config["judge_max_tokens"],
        ),
    ):
        breakdown = []
        for key in dict.fromkeys(config["generators"] + config["judges"]):
            model = model_lock["models"][key]
            pricing = model["pricing"]
            pin, pout = float(pricing["prompt"]), float(pricing["completion"])
            if any(
                float(t.get("min_prompt_tokens", 0)) <= max(gin, jin)
                for t in pricing.get("overrides", [])
            ):
                raise ValueError(
                    "Token assumption crosses a pricing tier; use a tier-aware estimate"
                )
            gen_calls = base_per_generator if key in config["generators"] else 0
            foil_calls = foil_per_model.get(key, 0)
            judge_calls = judge_per_model if key in config["judges"] else 0
            cost = (gen_calls + foil_calls) * (gin * pin + gout * pout)
            cost += judge_calls * (jin * pin + jout * pout)
            breakdown.append(
                {
                    "model": key,
                    "provider": model["provider"],
                    "generation_calls": gen_calls,
                    "foil_calls": foil_calls,
                    "judge_calls": judge_calls,
                    "estimated_usd": round(cost, 6),
                }
            )
        total = sum(row["estimated_usd"] for row in breakdown)
        scenarios.append(
            {
                "scenario": name,
                "assumed_tokens_per_call_including_reasoning": {
                    "generation_input": gin,
                    "generation_output": gout,
                    "judge_input": jin,
                    "judge_output": jout,
                },
                "estimated_inference_usd": round(total, 4),
                "with_10_percent_planning_margin_usd": round(total * 1.1, 4),
                "below_run_ceiling_with_margin": total * 1.1 <= config["budget_limit_usd"],
                "models": breakdown,
            }
        )
    return {
        "counts": counts,
        "pricing_checked_at": model_lock["checked_at"],
        "scenarios": scenarios,
        "warning": "Conditional scenarios, not completion guarantees or hard cost bounds. "
        "Actual prompts, reasoning, rates and pair yields vary. Payment/top-up fees "
        "are excluded. Keep the shared ledger ceiling and a provider-side spend cap.",
    }
