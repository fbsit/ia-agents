export type GenerationProvider = "auto" | "openai" | "anthropic";

export type ProviderAvailability = {
  openai: boolean;
  anthropic: boolean;
};

export const OPENAI_MODEL_OPTIONS = [
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.4-nano",
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4.1-nano",
  "gpt-4o",
  "gpt-4o-mini"
] as const;

export const ANTHROPIC_MODEL_OPTIONS = [
  "claude-sonnet-4-6",
  "claude-opus-4-6",
  "claude-haiku-4-5",
  "claude-3-7-sonnet-latest",
  "claude-3-5-sonnet-latest",
  "claude-3-5-haiku-latest"
] as const;

export function isProviderEnabled(provider: GenerationProvider, availability: ProviderAvailability): boolean {
  if (provider === "openai") {
    return availability.openai;
  }
  if (provider === "anthropic") {
    return availability.anthropic;
  }
  return availability.openai || availability.anthropic;
}

export function getModelOptions(provider: GenerationProvider, availability: ProviderAvailability): string[] {
  if (provider === "openai") {
    return availability.openai ? [...OPENAI_MODEL_OPTIONS] : [];
  }
  if (provider === "anthropic") {
    return availability.anthropic ? [...ANTHROPIC_MODEL_OPTIONS] : [];
  }

  if (availability.openai) {
    return [...OPENAI_MODEL_OPTIONS];
  }
  if (availability.anthropic) {
    return [...ANTHROPIC_MODEL_OPTIONS];
  }
  return [];
}

export function normalizeProvider(provider: string | null | undefined): GenerationProvider {
  if (provider === "openai" || provider === "anthropic" || provider === "auto") {
    return provider;
  }
  return "auto";
}

export function pickDefaultProvider(availability: ProviderAvailability): GenerationProvider {
  if (availability.openai) {
    return "openai";
  }
  if (availability.anthropic) {
    return "anthropic";
  }
  return "auto";
}

export function ensureModelInOptions(options: string[], currentModel: string): string[] {
  const model = currentModel.trim();
  if (!model) {
    return options;
  }
  if (options.includes(model)) {
    return options;
  }
  return [model, ...options];
}
