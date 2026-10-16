def merge_state(state, res):
    if res and isinstance(res, dict) and "data" in res:
        if not state: state = {}
        if "data" not in state: state["data"] = {}
        for k, v in res["data"].items():
            if isinstance(v, dict) and isinstance(state["data"].get(k), dict):
                state["data"][k].update(v)
            else:
                state["data"][k] = v
    return state
