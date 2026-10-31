/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { MCP } from '../../../../platform/mcp/common/modelContextProtocol.js';
import { ALL_PARTS } from '../../../services/saengineProject/common/saengineProject.js';

/*
 * What an AI assistant may do in a SAEngine window: the MCP tools and the commands it may run.
 * The descriptions are for the assistant (English, like every MCP tool schema); what the engineer
 * sees is localized in the contribution. Pure data and checks, so they are unit tested.
 */

/** Setting: the server starts with every window (it is off by default). */
export const ALLOW_CONTROL_SETTING = 'saengine.ai.allowControl';
/** Setting: the port to listen on; 0 picks a free one. */
export const PORT_SETTING = 'saengine.ai.port';

export interface IAiTool {
	readonly name: string;
	readonly title: string;
	readonly description: string;
	readonly inputSchema: IJSONSchema & { readonly type: 'object' };
	/** Changes the project: listed and callable only while edits are allowed. */
	readonly edits?: boolean;
	/** Only reads: never changes the window or the project. */
	readonly readOnly?: boolean;
}

const PART_IDS = ALL_PARTS.map(part => part.id);

export const RESULT_KINDS = ['design', 'fem', 'substructure', 'mep', 'boq'] as const;
export type ResultKind = typeof RESULT_KINDS[number];

export const AI_TOOLS: readonly IAiTool[] = [
	{
		name: 'get_project',
		title: 'Project info',
		description: 'The open SAEngine project: name, folder, type, and every part (Soil Report, Floor Plan, FEM, ...) with its status (notStarted, inProgress, done, stale, failed, error) and hint. Also the open editors and whether edits are allowed.',
		inputSchema: { type: 'object', properties: {}, additionalProperties: false },
		readOnly: true,
	},
	{
		name: 'list_editors',
		title: 'Open editors',
		description: 'The editors open in the window (title, file relative to the project, part, unsaved) and which one is active.',
		inputSchema: { type: 'object', properties: {}, additionalProperties: false },
		readOnly: true,
	},
	{
		name: 'open_part',
		title: 'Open a part',
		description: 'Opens a part of the project in its editor, as clicking it in the Project sidebar does.',
		inputSchema: {
			type: 'object',
			properties: { part: { type: 'string', enum: PART_IDS, description: 'The part id.' } },
			required: ['part'],
			additionalProperties: false,
		},
	},
	{
		name: 'open_file',
		title: 'Open a project file',
		description: 'Opens a file of the project (path relative to the project folder, e.g. "08 FEM/model.results/design-summary.json") in its editor.',
		inputSchema: {
			type: 'object',
			properties: { path: { type: 'string', description: 'Path relative to the project folder, with forward slashes.' } },
			required: ['path'],
			additionalProperties: false,
		},
	},
	{
		name: 'read_active_document',
		title: 'Read the active document',
		description: 'The document of the active editor as the engineer sees it, unsaved edits included (JSON parts are returned parsed), with the text selection and the selected model item (member, story, grid line or object type).',
		inputSchema: {
			type: 'object',
			properties: { maxChars: { type: 'integer', minimum: 1000, maximum: 2000000, description: 'Longest text returned (default 200000); longer documents are cut.' } },
			additionalProperties: false,
		},
		readOnly: true,
	},
	{
		name: 'read_results',
		title: 'Read results',
		description: 'A results summary of the project: "design" (design checks: checked, passed, failed, governing member), "fem" (the analysis run manifest), "substructure" (footing sizing summary), "mep" (MEP summary) or "boq" (the bill of quantities).',
		inputSchema: {
			type: 'object',
			properties: { kind: { type: 'string', enum: [...RESULT_KINDS] } },
			required: ['kind'],
			additionalProperties: false,
		},
		readOnly: true,
	},
	{
		name: 'list_commands',
		title: 'List commands',
		description: 'The SAEngine commands run_command may run (Run All, Design Reinforcement, Print Design Report, exports, ...), with what each does and whether it needs edits allowed.',
		inputSchema: { type: 'object', properties: {}, additionalProperties: false },
		readOnly: true,
	},
	{
		name: 'run_command',
		title: 'Run a command',
		description: 'Runs one SAEngine command from list_commands exactly as the menu does (the engineer sees any dialog it shows). Long commands such as Run All keep running after this returns; check get_project for the part statuses.',
		inputSchema: {
			type: 'object',
			properties: { command: { type: 'string', description: 'A command id from list_commands.' } },
			required: ['command'],
			additionalProperties: false,
		},
	},
	{
		name: 'screenshot',
		title: 'Screenshot',
		description: 'A picture of the SAEngine window as it is now (PNG).',
		inputSchema: { type: 'object', properties: {}, additionalProperties: false },
		readOnly: true,
	},
	{
		name: 'show_message',
		title: 'Show a message',
		description: 'Shows the engineer a notification in the window, marked as coming from the AI assistant (e.g. "Opening the Soil Report to check the bearing capacity").',
		inputSchema: {
			type: 'object',
			properties: {
				message: { type: 'string', maxLength: 500 },
				severity: { type: 'string', enum: ['info', 'warning'], description: 'Default info.' },
			},
			required: ['message'],
			additionalProperties: false,
		},
	},
	{
		name: 'reveal_element',
		title: 'Reveal an element',
		description: 'Selects and shows an item of the model in its editor, as clicking it does: a member of the floor plan (kind "member" with group and id, e.g. group "columns", id "C1"), a story (kind "story", id), a grid line (kind "gridLine", axis "x"/"y", label) or an object type (kind "objectType", id).',
		inputSchema: {
			type: 'object',
			properties: {
				kind: { type: 'string', enum: ['member', 'story', 'gridLine', 'objectType'] },
				group: { type: 'string', enum: ['columns', 'footings', 'walls', 'beams', 'slabs'] },
				id: { type: 'string' },
				axis: { type: 'string', enum: ['x', 'y'] },
				label: { type: 'string' },
			},
			required: ['kind'],
			additionalProperties: false,
		},
	},
	{
		name: 'set_json_value',
		title: 'Edit a part (JSON)',
		description: 'Changes one value in a JSON file of the project (e.g. "04 Objects/objects.json") through the editor, like typing it: the change is undoable (Ctrl+Z), shows at once in every view, and stays unsaved until the engineer saves. Only while the engineer allows edits.',
		inputSchema: {
			type: 'object',
			properties: {
				file: { type: 'string', description: 'A .json file relative to the project folder.' },
				path: { type: 'array', items: { type: ['string', 'integer'] }, description: 'JSON path to the value, e.g. ["stories", 0, "height"]. Missing objects are created.' },
				value: { description: 'The new value (any JSON). Omit with remove: true to delete the property.' },
				remove: { type: 'boolean', description: 'Delete the property or array item instead of setting it.' },
			},
			required: ['file', 'path'],
			additionalProperties: false,
		},
		edits: true,
	},
];

/** The tools offered while edits are (not) allowed. */
export function visibleTools(allowEdits: boolean): readonly IAiTool[] {
	return AI_TOOLS.filter(tool => allowEdits || !tool.edits);
}

export function toMcpTool(tool: IAiTool): MCP.Tool {
	return {
		name: tool.name,
		title: tool.title,
		description: tool.description,
		inputSchema: tool.inputSchema as MCP.Tool['inputSchema'],
		annotations: { title: tool.title, readOnlyHint: !!tool.readOnly, destructiveHint: false, openWorldHint: false },
	};
}

//#region Commands

export interface IAllowedCommand {
	readonly id: string;
	readonly description: string;
	/** Changes the engineer's model: only while edits are allowed. */
	readonly edits?: boolean;
	/** Arguments the command takes from the project (never from the assistant). */
	readonly projectArgs?: 'drawings';
}

/**
 * The commands an assistant may run, all as the menus run them: no arguments from the assistant,
 * so no file paths or scripts reach a command. Anything not here is refused (no shell, no
 * extensions, no settings, no file deletes).
 */
export const ALLOWED_COMMANDS: readonly IAllowedCommand[] = [
	{ id: 'saengine.runAll', description: 'Run All: saves the project, then runs the analysis and the design (can take long).' },
	{ id: 'saengine.runAll.cancel', description: 'Cancels Run All.' },
	{ id: 'saengine.runAll.showLog', description: 'Shows the Run All log.' },
	{ id: 'saengine.fem.runAnalysis', description: 'Runs the FEM analysis of the project.' },
	{ id: 'saengine.fem.runSelectedCases', description: 'Asks the engineer which load cases to run, then runs them.' },
	{ id: 'saengine.fem.showLog', description: 'Shows the analysis log.' },
	{ id: 'saengine.fem.showCharts', description: 'Opens the analysis charts of the last run.' },
	{ id: 'saengine.fem.pickMember', description: 'Asks the engineer for a member and shows its forces and design.' },
	{ id: 'saengine.fem.designReinforcement', description: 'Opens the design proposal preview (Design Reinforcement); applying it is the engineer\'s click.' },
	{ id: 'saengine.report.print', description: 'Builds the design report PDF in 11 Exports.' },
	{ id: 'saengine.drawings.generate', description: 'Generates the structural drawings (DXF) of the project in 11 Exports.', projectArgs: 'drawings' },
	{ id: 'saengine.floorPlan.exportDxf', description: 'Exports the floor plans as DXF.' },
	{ id: 'saengine.bim.exportIfc', description: 'Exports the building as IFC.' },
	{ id: 'saengine.boq.exportCsv', description: 'Exports the bill of quantities as CSV (asks where).' },
	{ id: 'saengine.boq.exportXlsx', description: 'Exports the bill of quantities with its costing and embodied carbon to Excel (asks where).' },
	{ id: 'saengine.project.showOverview', description: 'Opens the project overview.' },
	{ id: 'saengine.project.showExports', description: 'Opens the Exports page.' },
	{ id: 'saengine.project.showStart', description: 'Opens the Start page.' },
	{ id: 'saengine.project.showVersions', description: 'Opens the project versions.' },
	{ id: 'saengine.project.showImportReport', description: 'Opens the last structural import report.' },
	{ id: 'saengine.project.saveVersion', description: 'Saves a version of the project (asks for a message).' },
	{ id: 'saengine.project.exportArchive', description: 'Exports the project as a .civil archive (asks where).' },
	{ id: 'saengine.project.newBuilding', description: 'Opens the New Building wizard (generate a building); the engineer completes it.' },
	{ id: 'saengine.floorPlan.openMembersTable', description: 'Opens the members table of the floor plan.' },
	{ id: 'saengine.checkPythonRuntime', description: 'Checks the Python runtime the analysis uses.' },
	{ id: 'saengine.substructure.sizeAll', description: 'Sizes every footing in the Substructure editor.', edits: true },
	{ id: 'saengine.substructure.importFootings', description: 'Imports the footings from the floor plan into the Substructure part.', edits: true },
	{ id: 'saengine.soil.addBorehole', description: 'Adds a borehole to the Soil Report.', edits: true },
	{ id: 'undo', description: 'Undo the last edit in the active editor.', edits: true },
	{ id: 'redo', description: 'Redo the last undone edit in the active editor.', edits: true },
];

export type CommandCheck =
	| { readonly ok: true; readonly command: IAllowedCommand }
	| { readonly ok: false; readonly reason: 'notAllowed' | 'editsNotAllowed' };

export function checkCommand(id: string, allowEdits: boolean): CommandCheck {
	const command = ALLOWED_COMMANDS.find(c => c.id === id);
	if (!command) {
		return { ok: false, reason: 'notAllowed' };
	}
	if (command.edits && !allowEdits) {
		return { ok: false, reason: 'editsNotAllowed' };
	}
	return { ok: true, command };
}

//#endregion

//#region Arguments

/**
 * Checks tool arguments against the tool's schema (the subset the tools use: types, enums,
 * required, no unknown properties, string lengths, integer ranges). Returns the problems.
 */
export function validateArguments(tool: IAiTool, args: unknown): string[] {
	if (typeof args !== 'object' || args === null || Array.isArray(args)) {
		return ['arguments must be an object'];
	}
	const problems: string[] = [];
	const properties = tool.inputSchema.properties ?? {};
	for (const name of tool.inputSchema.required ?? []) {
		if (!Object.prototype.hasOwnProperty.call(args, name)) {
			problems.push(`missing "${name}"`);
		}
	}
	for (const [name, value] of Object.entries(args)) {
		const schema = properties[name];
		if (!schema) {
			problems.push(`unknown argument "${name}"`);
			continue;
		}
		problems.push(...validateValue(schema, value, name));
	}
	return problems;
}

function validateValue(schema: IJSONSchema, value: unknown, name: string): string[] {
	if (schema.type !== undefined) {
		const types = Array.isArray(schema.type) ? schema.type : [schema.type];
		if (!types.some(type => hasType(value, type))) {
			return [`"${name}" must be ${types.join(' or ')}`];
		}
	}
	if (schema.enum && !schema.enum.includes(value)) {
		return [`"${name}" must be one of ${schema.enum.map(v => JSON.stringify(v)).join(', ')}`];
	}
	if (typeof value === 'string' && schema.maxLength !== undefined && value.length > schema.maxLength) {
		return [`"${name}" is longer than ${schema.maxLength} characters`];
	}
	if (typeof value === 'number' && ((schema.minimum !== undefined && value < schema.minimum) || (schema.maximum !== undefined && value > schema.maximum))) {
		return [`"${name}" must be between ${schema.minimum} and ${schema.maximum}`];
	}
	if (Array.isArray(value) && schema.items && !Array.isArray(schema.items) && typeof schema.items === 'object') {
		const items = schema.items;
		return value.flatMap((item, index) => validateValue(items, item, `${name}[${index}]`));
	}
	return [];
}

function hasType(value: unknown, type: string): boolean {
	switch (type) {
		case 'string': return typeof value === 'string';
		case 'integer': return typeof value === 'number' && Number.isInteger(value);
		case 'number': return typeof value === 'number' && Number.isFinite(value);
		case 'boolean': return typeof value === 'boolean';
		case 'array': return Array.isArray(value);
		case 'object': return typeof value === 'object' && value !== null && !Array.isArray(value);
		case 'null': return value === null;
		default: return false;
	}
}

//#endregion

/**
 * A project-relative path an assistant gave, made safe: forward slashes, no drive, no leading
 * slash, no "." or ".." segments. Undefined when it would leave the project.
 */
export function safeRelativePath(path: string): string | undefined {
	const segments = path.replace(/\\/g, '/').split('/').filter(segment => segment.length > 0);
	if (segments.length === 0 || /^[a-zA-Z]:/.test(path) || path.startsWith('/') || path.startsWith('\\')) {
		return undefined;
	}
	if (segments.some(segment => segment === '.' || segment === '..' || segment.includes(':') || segment.includes('\0'))) {
		return undefined;
	}
	return segments.join('/');
}
