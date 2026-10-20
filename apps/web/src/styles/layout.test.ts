import { readFileSync } from "node:fs";
import { parse } from "postcss";
import { describe, expect, it } from "vitest";

function declarations(file: string, selector: string) {
  const rules: Record<string, string>[] = [];
  parse(readFileSync(new URL(file, import.meta.url), "utf8")).walkRules(selector, rule => {
    const values: Record<string, string> = {};
    rule.walkDecls(declaration => { values[declaration.prop] = declaration.value; });
    rules.push(values);
  });
  return rules;
}

describe("workspace width", () => {
  it.each([
    ["../styles.css", ".workspace-page"],
    ["../styles.css", ".workspace-model-surface"],
    ["../styles.css", ".workspace-list-surface"],
    ["../styles.css", ".camera-panel"],
    ["./workspace-settings.css", ".settings-page"],
    ["./team.css", ".team-page"],
    ["./integrations.css", ".integrations-page"],
    ["./evaluations.css", ".evaluations-page"],
  ])("lets %s %s fill the available content track", (file, selector) => {
    const rules = declarations(file, selector);
    expect(rules.length).toBeGreaterThan(0);
    expect(rules[0].width).toBe("100%");
    for (const rule of rules) {
      expect([undefined, "none", "100%"]).toContain(rule["max-width"]);
    }
  });

  it("does not constrain the idle camera at tablet widths", () => {
    for (const rule of declarations("../styles.css", ".camera-panel.is-idle")) {
      expect([undefined, "none", "100%"]).toContain(rule["max-width"]);
    }
  });

  it("keeps individual settings and invitation forms readable", () => {
    expect(declarations("./workspace-settings.css", ".settings-form")[0]["max-width"]).toBe("680px");
    expect(declarations("./team.css", ".invitation-page")[0].width).toBe("min(100%,640px)");
  });
});
