/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/*
 * Bug reports, feedback and the opt-in diagnostics bundle (U2). Pure: what a report says, how a
 * diagnostics bundle is anonymised and how a report becomes the destination's request. The
 * workbench side (feedback.contribution.ts) collects the values and shows the form.
 */

/**
 * Where reports go: a public report as a pre-filled GitHub issue opened in the browser (the
 * repository's issue templates in .github/ISSUE_TEMPLATE), a private one as an e-mail to the
 * developers opened in the engineer's mail program. Nothing is sent until the engineer submits
 * it there.
 */
export const FEEDBACK_DESTINATION = {
	kind: 'githubIssue',
	url: 'https://github.com/The-Studio-of-Sadiq/SAEngine/issues/new',
	/** Private reports: the developers' address, also named in the issue chooser (config.yml). */
	privateEmail: 'publicrelations@thestudioofsadiq.tech',
} as const;

/** Who can read a report: anyone (a GitHub issue) or only the developers (an e-mail). */
export type FeedbackVisibility = 'public' | 'private';

/** Setting: help the developers with an anonymised diagnostics bundle (off by default). */
export const DIAGNOSTICS_SETTING = 'saengine.diagnostics.shareWithDevelopers';

/** Commands. */
export const REPORT_BUG_COMMAND = 'saengine.feedback.reportBug';
export const SEND_FEEDBACK_COMMAND = 'saengine.feedback.send';
export const CREATE_DIAGNOSTICS_COMMAND = 'saengine.diagnostics.create';

export type FeedbackKind = 'bug' | 'feedback' | 'feature';

export interface IFeedbackForm {
	readonly kind: FeedbackKind;
	readonly title: string;
	readonly description: string;
	/** Bugs: how to make it happen again. */
	readonly steps: string;
	/** Optional: for the developers to answer (in a public report it is shown in the issue). */
	readonly email: string;
	/** Public GitHub issue, or a private e-mail to the developers. */
	readonly visibility?: FeedbackVisibility;
}

/** What goes with a report, each only when the engineer ticks it. */
export interface IFeedbackAttachments {
	/** The anonymised diagnostics bundle (its JSON text). */
	readonly diagnostics?: string;
	/** The project's status summary: each part's state, no names, paths or values. */
	readonly projectStatus?: string;
	/** Files the engineer attaches by hand (a screenshot, an exported project): their names. */
	readonly files?: readonly string[];
}

/** The longest URL sent to the browser; a longer report goes by the clipboard. */
export const MAX_URL_LENGTH = 7500;

/** The longest mailto: link (Windows hands at most about 2,000 characters to the mail program). */
export const MAX_MAILTO_LENGTH = 1900;

/** The kind's label, as the form and the issue's title name it. */
export function kindLabel(kind: FeedbackKind): string {
	switch (kind) {
		case 'bug': return localize('feedback.kind.bug', "Bug");
		case 'feature': return localize('feedback.kind.feature', "Feature request");
		default: return localize('feedback.kind.feedback', "Feedback");
	}
}

/** Why the form cannot be sent yet (an empty description), or undefined. */
export function formProblem(form: IFeedbackForm): string | undefined {
	if (!form.title.trim()) {
		return localize('feedback.noTitle', "Give the report a short title.");
	}
	if (!form.description.trim()) {
		return localize('feedback.noDescription', "Describe what happened or what you would like.");
	}
	if (form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
		return localize('feedback.badEmail', "The e-mail address does not look right (or leave it empty).");
	}
	return undefined;
}

/** The issue's title and body exactly as they will be sent: the form shows this before sending. */
export function buildReport(form: IFeedbackForm, attachments: IFeedbackAttachments, app: { readonly version: string; readonly os: string }): { readonly title: string; readonly body: string } {
	const sections: string[] = [];
	sections.push(`**${kindLabel(form.kind)}** · SAEngine ${app.version} · ${app.os}`);
	sections.push(`### ${form.kind === 'bug' ? 'What happened' : 'Description'}\n\n${form.description.trim()}`);
	if (form.kind === 'bug' && form.steps.trim()) {
		sections.push(`### Steps to reproduce\n\n${form.steps.trim()}`);
	}
	if (form.email.trim()) {
		sections.push(`### Contact\n\n${form.email.trim()}`);
	}
	if (attachments.projectStatus) {
		sections.push(`### Project status (no names or values)\n\n\`\`\`\n${attachments.projectStatus}\n\`\`\``);
	}
	if (attachments.diagnostics) {
		sections.push(`<details><summary>Diagnostics bundle (anonymised)</summary>\n\n\`\`\`json\n${attachments.diagnostics}\n\`\`\`\n\n</details>`);
	}
	if (attachments.files?.length) {
		sections.push(`### Attached by the reporter\n\n${attachments.files.map(f => `- ${f}`).join('\n')}`);
	}
	sections.push('_Sent with Help › Report a Bug / Send Feedback in SAEngine._');
	return { title: `[${kindLabel(form.kind)}] ${form.title.trim()}`, body: sections.join('\n\n') };
}

/**
 * The request to the destination: a GitHub "new issue" URL with the title and body. A report
 * too long for a URL is sent with a short body asking to paste it (`clipboard`: put the full
 * body in the clipboard first).
 */
export function issueRequest(report: { readonly title: string; readonly body: string }, base: string = FEEDBACK_DESTINATION.url): { readonly url: string; readonly clipboard?: string } {
	const full = `${base}?title=${encodeURIComponent(report.title)}&body=${encodeURIComponent(report.body)}`;
	if (full.length <= MAX_URL_LENGTH) {
		return { url: full };
	}
	const note = localize('feedback.pasteNote', "The report is too long for the link: SAEngine copied it to the clipboard. Paste it here (Ctrl+V), replacing this line.");
	return { url: `${base}?title=${encodeURIComponent(report.title)}&body=${encodeURIComponent(note)}`, clipboard: report.body };
}

/**
 * The private request: a mailto: link to the developers with the title as the subject and the
 * report as the body. A report too long for the link goes by the clipboard, as in
 * {@link issueRequest}.
 */
export function emailRequest(report: { readonly title: string; readonly body: string }, address: string = FEEDBACK_DESTINATION.privateEmail): { readonly url: string; readonly clipboard?: string } {
	const subject = `SAEngine ${report.title}`;
	const full = `mailto:${address}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(report.body)}`;
	if (full.length <= MAX_MAILTO_LENGTH) {
		return { url: full };
	}
	const note = localize('feedback.pasteMailNote', "The report is too long for the link: SAEngine copied it to the clipboard. Paste it here (Ctrl+V), replacing this line.");
	return { url: `mailto:${address}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(note)}`, clipboard: report.body };
}

/** What anonymising replaces, so the bundle names no person, computer, project or folder. */
export interface IAnonymiseContext {
	/** The user's home folder. */
	readonly home?: string;
	/** The open project's folder and name. */
	readonly projectRoot?: string;
	readonly projectName?: string;
	/** The user's name on this computer. */
	readonly userName?: string;
}

function escapeRegExp(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * `text` with personal details replaced: the project's folder and name, the home folder and the
 * user's name (with either slash), e-mail addresses, and any other user folder of Windows, macOS
 * or Linux.
 */
export function anonymise(text: string, context: IAnonymiseContext): string {
	let out = text;
	const variants = (path: string | undefined) => path ? [...new Set([path, path.replace(/\\/g, '/'), path.replace(/\//g, '\\'), path.replace(/\\/g, '\\\\')])] : [];
	for (const [value, token] of [
		...variants(context.projectRoot).map(v => [v, '<project>'] as const),
		...variants(context.home).map(v => [v, '<home>'] as const),
	]) {
		if (value.length > 2) {
			out = out.replace(new RegExp(escapeRegExp(value), 'gi'), token);
		}
	}
	out = out.replace(/[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\s"']+/gi, '<home>');
	out = out.replace(/\/(?:Users|home)\/[^/\s"']+/g, '<home>');
	out = out.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '<email>');
	for (const [value, token] of [[context.projectName, '<project name>'], [context.userName, '<user>']] as const) {
		if (value && value.trim().length > 2) {
			out = out.replace(new RegExp(`\\b${escapeRegExp(value.trim())}\\b`, 'gi'), token);
		}
	}
	return out;
}

/** One unexpected error the window recorded, for the bundle. */
export interface IRecordedError {
	readonly time: string;
	readonly message: string;
	readonly stack?: string;
}

/** The values a diagnostics bundle holds before anonymising: no project files, names or values. */
export interface IDiagnosticsInput {
	readonly created: string;
	readonly app: { readonly version: string; readonly commit?: string; readonly date?: string };
	readonly os: { readonly platform: string; readonly release: string; readonly arch: string };
	readonly runtime: { readonly [name: string]: string | undefined };
	readonly codePack?: string;
	readonly displayLanguage?: string;
	readonly developerMode: boolean;
	readonly lastSessionEndedUnexpectedly: boolean;
	readonly projectOpen: boolean;
	readonly errors: readonly IRecordedError[];
}

/** The anonymised diagnostics bundle as the engineer reviews it and as it is sent (JSON). */
export function diagnosticsBundle(input: IDiagnosticsInput, context: IAnonymiseContext): string {
	const bundle = {
		schema: 'saengine.diagnostics/1',
		note: 'Anonymised by SAEngine: no project files, names, folders or values. Sent only when you choose to.',
		...input,
		errors: input.errors.slice(-20),
	};
	return anonymise(JSON.stringify(bundle, undefined, 2), context);
}

/** The project's status summary: each part's state, nothing of its content. */
export function projectStatusSummary(statuses: readonly { readonly part: string; readonly state: string }[]): string {
	return statuses.map(s => `${s.part}: ${s.state}`).join('\n');
}
