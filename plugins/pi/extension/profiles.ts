export type RequestedProfile =
	| "standard"
	| "safe-routed"
	| "auto"
	| "safe-small"
	| "minicpm-list";

export type EffectiveProfile = Exclude<RequestedProfile, "auto">;
export type ModelFamily = "gemma" | "minicpm" | "ornith" | "unknown";

export interface ModelIdentity {
	id?: string;
	name?: string;
	provider?: string;
}

export interface ProfileDecision {
	requested: RequestedProfile;
	effective: EffectiveProfile;
	family: ModelFamily;
	model: string;
	reason: string;
}

export function requestedProfile(value: string | undefined): RequestedProfile {
	if (value === undefined || value === "" || value === "measured") return "standard";
	if (["standard", "safe-routed", "auto", "safe-small", "minicpm-list"].includes(value)) {
		return value as RequestedProfile;
	}
	throw new Error(
		`Unknown INCISE_PROFILE ${JSON.stringify(value)}. ` +
		"Use standard, safe-routed, auto, safe-small, or minicpm-list.",
	);
}

export function modelFamily(
	model: ModelIdentity | undefined,
	override?: string,
): ModelFamily {
	if (override !== undefined && override !== "") {
		const normalized = override.toLowerCase();
		if (normalized === "gemma" || normalized === "minicpm" || normalized === "ornith" || normalized === "unknown") {
			return normalized;
		}
		throw new Error(
			`Unknown INCISE_MODEL_FAMILY ${JSON.stringify(override)}. Use gemma, minicpm, ornith, or unknown.`,
		);
	}
	const identity = `${model?.provider ?? ""} ${model?.id ?? ""} ${model?.name ?? ""}`.toLowerCase();
	if (/mini[-_ ]?cpm/.test(identity)) return "minicpm";
	if (/gemma/.test(identity)) return "gemma";
	if (/ornith/.test(identity)) return "ornith";
	return "unknown";
}

function modelLabel(model: ModelIdentity | undefined): string {
	if (!model) return "unavailable";
	return model.id || model.name || model.provider || "unknown";
}

export function selectProfile(
	requested: RequestedProfile,
	model: ModelIdentity | undefined,
	familyOverride?: string,
): ProfileDecision {
	const family = modelFamily(model, familyOverride);
	const label = modelLabel(model);
	if (requested !== "auto") {
		return {
			requested,
			effective: requested,
			family,
			model: label,
			reason: `explicit INCISE_PROFILE=${requested}`,
		};
	}
	if (family === "gemma" || family === "ornith") {
		return {
			requested,
			effective: "safe-routed",
			family,
			model: label,
			reason: family === "gemma"
				? "auto selected the measured Gemma routing capabilities"
				: "auto selected the measured Ornith routing capabilities",
		};
	}
	return {
		requested,
		effective: "standard",
		family,
		model: label,
		reason: family === "minicpm"
			? "auto kept the standard profile because no general MiniCPM profile has passed evaluation"
			: "auto kept the model-agnostic standard profile for an unknown model family",
	};
}
