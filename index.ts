// Supabase Edge Function: writes a Study Coach report from the signed-in user's real results.
// Secrets (set with `supabase secrets set`): GEMINI_API_KEY | OPENROUTER_API_KEY (+OPENROUTER_MODEL) | OPENAI_COMPAT_API_KEY (+_BASE_URL, _MODEL)
import { createClient } from "npm:@supabase/supabase-js@2.45.4";

const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info", "Content-Type": "application/json" };
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: cors });

async function callModel(provider: string, prompt: string): Promise<{ text: string; model: string }> {
  if (provider === "gemini") {
    const key = Deno.env.get("GEMINI_API_KEY"); if (!key) throw new Error("GEMINI_API_KEY is not set");
    const model = Deno.env.get("GEMINI_MODEL") ?? "gemini-2.0-flash";
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, { method: "POST", headers: { "x-goog-api-key": key, "content-type": "application/json" },
      body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }], generationConfig: { temperature: 0.3 } }) });
    if (!r.ok) throw new Error(`Gemini error ${r.status}`);
    return { text: (await r.json()).candidates[0].content.parts[0].text, model };
  }
  const cfg = provider === "openrouter"
    ? { key: Deno.env.get("OPENROUTER_API_KEY"), base: "https://openrouter.ai/api/v1", model: Deno.env.get("OPENROUTER_MODEL") }
    : { key: Deno.env.get("OPENAI_COMPAT_API_KEY"), base: Deno.env.get("OPENAI_COMPAT_BASE_URL"), model: Deno.env.get("OPENAI_COMPAT_MODEL") };
  if (!cfg.key || !cfg.base || !cfg.model) throw new Error(`${provider} is not fully configured (key, base URL and model are required)`);
  const r = await fetch(cfg.base.replace(/\/$/, "") + "/chat/completions", { method: "POST", headers: { Authorization: `Bearer ${cfg.key}`, "content-type": "application/json" },
    body: JSON.stringify({ model: cfg.model, temperature: 0.3, messages: [{ role: "user", content: prompt }] }) });
  if (!r.ok) throw new Error(`${provider} error ${r.status}`);
  return { text: (await r.json()).choices[0].message.content, model: cfg.model };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  try {
    const auth = req.headers.get("Authorization") ?? "";
    const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!, { global: { headers: { Authorization: auth } } });
    const { data: { user } } = await sb.auth.getUser();
    if (!user) return json({ error: "Not signed in" }, 401);
    const { attempt_id } = await req.json();
    if (!attempt_id) return json({ error: "attempt_id is required" }, 400);

    // Row Level Security means these queries can only return this user's own data.
    const { data: att } = await sb.from("attempts").select("score,max_score,total_elapsed_seconds,active_seconds,tests(name,question_count)").eq("id", attempt_id).eq("status", "submitted").single();
    if (!att) return json({ error: "Submitted attempt not found" }, 404);
    const { data: rows } = await sb.from("attempt_responses").select("is_correct,active_seconds,questions(difficulty,subjects(name),chapters(name),topics(name))").eq("attempt_id", attempt_id);
    const by = (k: (r: any) => string | undefined) => { const m: Record<string, { n: number; c: number; w: number; sec: number }> = {};
      for (const r of rows ?? []) { const key = k(r) ?? "Unclassified"; const g = (m[key] ??= { n: 0, c: 0, w: 0, sec: 0 }); g.n++; g.sec += Number(r.active_seconds) || 0; if (r.is_correct === true) g.c++; if (r.is_correct === false) g.w++; } return m; };
    const summary = { test: att.tests, score: att.score, max_score: att.max_score, total_seconds: att.total_elapsed_seconds, active_seconds: att.active_seconds,
      by_subject: by((r) => r.questions?.subjects?.name), by_chapter: by((r) => r.questions?.chapters?.name), by_topic: by((r) => r.questions?.topics?.name), by_difficulty: by((r) => r.questions?.difficulty) };

    const { data: s } = await sb.from("user_settings").select("ai_provider").eq("user_id", user.id).single();
    const provider = s?.ai_provider ?? "gemini";
    const prompt = `You are a JEE study coach. Use ONLY the JSON data below. Never invent scores, topics or history. If the sample for a chapter is small (under 5 questions), say the evidence is thin.
Write: overall performance; strongest chapters; weakest chapters and topics; time-management issues; revision priorities; a practical 7-day plan. Name the numbers you rely on.
DATA: ${JSON.stringify(summary)}`;
    const { text, model } = await callModel(provider, prompt);
    await sb.from("ai_reports").insert({ user_id: user.id, attempt_id, provider, model, input_summary: summary, report_markdown: text });
    return json({ report: text });
  } catch (e) { return json({ error: (e as Error).message }, 500); }
});
