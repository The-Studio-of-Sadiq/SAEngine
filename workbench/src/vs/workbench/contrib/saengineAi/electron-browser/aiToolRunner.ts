/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { encodeBase64, VSBuffer } from '../../../../base/common/buffer.js';
import { JSONPath } from '../../../../base/common/json.js';
import { removeProperty, setProperty } from '../../../../base/common/jsonEdit.js';
import { extUriBiasedIgnorePathCase, joinPath } from '../../../../base/common/resources.js';
import { timeout } from '../../../../base/common/async.js';
import { URI } from '../../../../base/common/uri.js';
import { isCodeEditor } from '../../../../editor/browser/editorBrowser.js';
import { Range } from '../../../../editor/common/core/range.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { MCP } from '../../../../platform/mcp/common/modelContextProtocol.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { EditorResourceAccessor, EditorsOrder } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ModelSelection, ISaengineModelSelectionService } from '../../../services/saengineProject/common/modelSelection.js';
import { DESIGN_SUMMARY_FILE, FEM_RESULTS_FOLDER, FEM_RESULTS_MANIFEST, ISaenginePartStatusService, MEP_SUMMARY_FILE, SUBSTRUCTURE_SUMMARY_FILE } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { openOwner } from '../../saengineModel/browser/projectDocuments.js';
import { generateArgs } from '../../saengineProject/browser/drawingsModel.js';
import { openPart, partName } from '../../saengineProject/browser/projectParts.js';
import { AI_TOOLS, ALLOWED_COMMANDS, checkCommand, IAiTool, ResultKind, safeRelativePath, validateArguments } from '../common/aiTools.js';

/** How long run_command waits for a command before reporting it as still running [ms]. */
const COMMAND_WAIT = 3000;
/** Longest text returned by default [chars]. */
const DEFAULT_MAX_CHARS = 200_000;
/** Widest screenshot sent [px]: larger windows are scaled down. */
const SCREENSHOT_WIDTH = 1600;

/** The source the selection service records for selections made by the assistant. */
export const AI_SELECTION_SOURCE = 'aiAssistant';

/** A tool's failure the assistant can act on (bad argument, no project): returned as an error result. */
class ToolError extends Error { }

/**
 * Runs the assistant's tool calls in the window, each through the service or command the UI uses
 * for the same thing. Whether edits are allowed is the controller's (it asks `allowEdits()`).
 */
export class AiToolRunner {

	constructor(
		private readonly allowEdits: () => boolean,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly partStatusService: ISaenginePartStatusService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
		@ICommandService private readonly commandService: ICommandService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@INativeHostService private readonly nativeHostService: INativeHostService,
		@INotificationService private readonly notificationService: INotificationService,
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
	) { }

	async call(name: string, args: Record<string, unknown>): Promise<MCP.CallToolResult> {
		const tool = AI_TOOLS.find(t => t.name === name);
		if (!tool) {
			return errorResult(`Unknown tool "${name}".`);
		}
		if (tool.edits && !this.allowEdits()) {
			return errorResult('Edits are not allowed in this window. Ask the engineer to choose "Allow AI Edits" (status bar: AI).');
		}
		const problems = validateArguments(tool, args);
		if (problems.length) {
			return errorResult(`Invalid arguments: ${problems.join('; ')}.`);
		}
		try {
			return await this.run(tool, args);
		} catch (error) {
			return errorResult(error instanceof ToolError ? error.message : `Failed: ${error instanceof Error ? error.message : String(error)}`);
		}
	}

	private run(tool: IAiTool, args: Record<string, unknown>): Promise<MCP.CallToolResult> {
		switch (tool.name) {
			case 'get_project': return this.getProject();
			case 'list_editors': return this.listEditors();
			case 'open_part': return this.openPart(args.part as string);
			case 'open_file': return this.openFile(args.path as string);
			case 'read_active_document': return this.readActiveDocument((args.maxChars as number | undefined) ?? DEFAULT_MAX_CHARS);
			case 'read_results': return this.readResults(args.kind as ResultKind);
			case 'list_commands': return this.listCommands();
			case 'run_command': return this.runCommand(args.command as string);
			case 'screenshot': return this.screenshot();
			case 'show_message': return this.showMessage(args.message as string, args.severity === 'warning' ? Severity.Warning : Severity.Info);
			case 'reveal_element': return this.reveal(args);
			case 'set_json_value': return this.setJsonValue(args.file as string, args.path as JSONPath, args.value, args.remove === true);
		}
		throw new ToolError(`Tool "${tool.name}" is not implemented.`);
	}

	private project(): ISaengineProject {
		const project = this.projectService.project;
		if (!project) {
			throw new ToolError('No SAEngine project is open in this window. Ask the engineer to open one.');
		}
		return project;
	}

	private relative(project: ISaengineProject, resource: URI | undefined): string | undefined {
		return resource && extUriBiasedIgnorePathCase.isEqualOrParent(resource, project.root)
			? extUriBiasedIgnorePathCase.relativePath(project.root, resource)
			: undefined;
	}

	private resolve(project: ISaengineProject, path: string): URI {
		const safe = safeRelativePath(path);
		if (!safe) {
			throw new ToolError(`"${path}" is not a path inside the project.`);
		}
		return joinPath(project.root, safe);
	}

	private async getProject(): Promise<MCP.CallToolResult> {
		const project = this.projectService.project;
		if (!project) {
			return jsonResult({ project: null, note: 'No project is open; the window shows the Start page.' });
		}
		return jsonResult({
			name: project.name,
			folder: project.root.fsPath,
			type: project.type,
			parts: this.projectService.parts.map((part, index) => {
				const status = this.partStatusService.statusOf(part.id);
				return {
					number: index + 1,
					id: part.id,
					name: partName(part),
					folder: part.folder,
					mainFile: part.mainFile,
					state: status?.state,
					status: status?.text,
					hint: status?.hint,
				};
			}),
			editors: this.editorList(project),
			editsAllowed: this.allowEdits(),
		});
	}

	private editorList(project: ISaengineProject | undefined) {
		const active = this.editorService.activeEditor;
		return this.editorService.getEditors(EditorsOrder.SEQUENTIAL).map(({ editor }) => {
			const resource = EditorResourceAccessor.getOriginalUri(editor);
			const path = project ? this.relative(project, resource) : undefined;
			return {
				title: editor.getName(),
				file: path,
				part: path ? this.projectService.parts.find(p => path.toLowerCase().startsWith(p.folder.toLowerCase() + '/'))?.id : undefined,
				unsaved: editor.isDirty(),
				active: editor === active,
			};
		});
	}

	private async listEditors(): Promise<MCP.CallToolResult> {
		return jsonResult({ editors: this.editorList(this.projectService.project) });
	}

	private async openPart(id: string): Promise<MCP.CallToolResult> {
		const project = this.project();
		const part = this.projectService.parts.find(p => p.id === id);
		if (!part) {
			throw new ToolError(`This project has no part "${id}" (its parts: ${this.projectService.parts.map(p => p.id).join(', ')}).`);
		}
		await openPart(project, part, { editorService: this.editorService, fileService: this.fileService, openerService: this.openerService, commandService: this.commandService });
		return textResult(`Opened ${partName(part)}.`);
	}

	private async openFile(path: string): Promise<MCP.CallToolResult> {
		const project = this.project();
		const resource = this.resolve(project, path);
		if (!await this.fileService.exists(resource)) {
			throw new ToolError(`No file "${path}" in the project.`);
		}
		await this.editorService.openEditor({ resource, options: { pinned: true } });
		return textResult(`Opened ${path}.`);
	}

	private async readActiveDocument(maxChars: number): Promise<MCP.CallToolResult> {
		const editor = this.editorService.activeEditor;
		const resource = EditorResourceAccessor.getOriginalUri(editor);
		if (!editor || !resource) {
			return jsonResult({ editor: editor?.getName() ?? null, note: 'The active editor has no document.', modelSelection: this.selectionService.selection ?? null });
		}
		const project = this.projectService.project;
		const path = project ? this.relative(project, resource) : undefined;
		if (!path) {
			throw new ToolError('The active editor shows a file outside the project; only project files are read.');
		}
		const reference = await this.textModelService.createModelReference(resource);
		try {
			const model = reference.object.textEditorModel;
			const text = model.getValue();
			const truncated = text.length > maxChars;
			let document: unknown = undefined;
			if (!truncated && /\.(json|osmodel)$/i.test(path)) {
				try {
					document = JSON.parse(text);
				} catch {
					// Invalid JSON while the engineer types: return the text.
				}
			}
			const control = this.editorService.activeTextEditorControl;
			const selection = isCodeEditor(control) && control.getModel() === model ? control.getSelection() : null;
			return jsonResult({
				editor: editor.getName(),
				file: path,
				unsaved: editor.isDirty(),
				textSelection: selection && !selection.isEmpty() ? { range: selection, text: model.getValueInRange(selection) } : null,
				modelSelection: this.selectionService.selection ?? null,
				truncated,
				...(document !== undefined ? { document } : { text: truncated ? text.slice(0, maxChars) : text }),
			});
		} finally {
			reference.dispose();
		}
	}

	private async readResults(kind: ResultKind): Promise<MCP.CallToolResult> {
		const project = this.project();
		const file = resultFile(kind);
		if (!file) {
			throw new ToolError(`Unknown results "${kind}".`);
		}
		const resource = joinPath(project.root, ...file.split('/'));
		let text: string;
		try {
			text = (await this.fileService.readFile(resource)).value.toString();
		} catch {
			return jsonResult({ kind, file, available: false, note: 'Not computed yet (see the part statuses in get_project).' });
		}
		const truncated = text.length > DEFAULT_MAX_CHARS;
		let results: unknown = undefined;
		if (!truncated) {
			try {
				results = JSON.parse(text);
			} catch {
				// Return the text.
			}
		}
		return jsonResult({ kind, file, available: true, truncated, ...(results !== undefined ? { results } : { text: text.slice(0, DEFAULT_MAX_CHARS) }) });
	}

	private async listCommands(): Promise<MCP.CallToolResult> {
		const allowEdits = this.allowEdits();
		return jsonResult({
			commands: ALLOWED_COMMANDS.filter(c => !!CommandsRegistry.getCommand(c.id)).map(c => ({
				command: c.id,
				description: c.description,
				needsEdits: !!c.edits,
				available: !c.edits || allowEdits,
			})),
		});
	}

	private async runCommand(id: string): Promise<MCP.CallToolResult> {
		const check = checkCommand(id, this.allowEdits());
		if (!check.ok) {
			throw new ToolError(check.reason === 'editsNotAllowed'
				? `"${id}" changes the model; edits are not allowed in this window.`
				: `"${id}" is not a command an assistant may run (see list_commands).`);
		}
		if (!CommandsRegistry.getCommand(id)) {
			throw new ToolError(`"${id}" is not available in this window.`);
		}
		const args = check.command.projectArgs === 'drawings' ? [generateArgs(this.project().root.fsPath)] : [];
		const run = this.commandService.executeCommand(id, ...args);
		const outcome = await Promise.race([
			run.then(() => 'done' as const),
			timeout(COMMAND_WAIT).then(() => 'running' as const),
		]);
		if (outcome === 'running') {
			run.catch(() => { /* reported by the command itself */ });
			return textResult(`${id} started and is still running (the engineer sees its progress). Call get_project to follow the part statuses.`);
		}
		return textResult(`${id} done.`);
	}

	private async screenshot(): Promise<MCP.CallToolResult> {
		const jpeg = await this.nativeHostService.getScreenshot();
		if (!jpeg) {
			throw new ToolError('Could not take a screenshot of the window.');
		}
		try {
			return { content: [{ type: 'image', data: await toPng(jpeg), mimeType: 'image/png' }] };
		} catch {
			return { content: [{ type: 'image', data: encodeBase64(jpeg), mimeType: 'image/jpeg' }] };
		}
	}

	private async showMessage(message: string, severity: Severity): Promise<MCP.CallToolResult> {
		// Always marked as the assistant's, so it cannot pass for SAEngine's own message.
		this.notificationService.notify({ severity, message: localize('aiMessage', "AI assistant: {0}", message), source: localize('aiSource', "AI Assistant") });
		return textResult('Shown.');
	}

	private async reveal(args: Record<string, unknown>): Promise<MCP.CallToolResult> {
		const project = this.project();
		let selection: ModelSelection;
		switch (args.kind) {
			case 'member':
				if (typeof args.group !== 'string' || typeof args.id !== 'string') {
					throw new ToolError('A member needs "group" and "id".');
				}
				selection = { kind: 'member', group: args.group as 'columns', id: args.id };
				break;
			case 'gridLine':
				if ((args.axis !== 'x' && args.axis !== 'y') || typeof args.label !== 'string') {
					throw new ToolError('A grid line needs "axis" and "label".');
				}
				selection = { kind: 'gridLine', axis: args.axis, label: args.label };
				break;
			case 'story':
			case 'objectType':
				if (typeof args.id !== 'string') {
					throw new ToolError(`A ${args.kind} needs "id".`);
				}
				selection = { kind: args.kind, id: args.id };
				break;
			default:
				throw new ToolError(`Unknown kind "${String(args.kind)}".`);
		}
		await openOwner(selection, undefined, project.root, this.editorService);
		this.selectionService.setSelection(selection, AI_SELECTION_SOURCE);
		return textResult('Revealed.');
	}

	private async setJsonValue(file: string, path: JSONPath, value: unknown, remove: boolean): Promise<MCP.CallToolResult> {
		const project = this.project();
		if (!/\.json$/i.test(file)) {
			throw new ToolError('Only .json files of the project can be edited.');
		}
		if (!remove && value === undefined) {
			throw new ToolError('Give "value", or "remove": true.');
		}
		const resource = this.resolve(project, file);
		if (!await this.fileService.exists(resource)) {
			throw new ToolError(`No file "${file}" in the project.`);
		}
		// The shared text model every editor and view uses: the edit is on the undo stack and stays unsaved.
		const reference = await this.textModelService.createModelReference(resource);
		try {
			const model = reference.object.textEditorModel;
			const text = model.getValue();
			try {
				JSON.parse(text);
			} catch {
				throw new ToolError(`${file} is not valid JSON now; it is not edited.`);
			}
			const options = model.getOptions();
			const formatting = { tabSize: options.tabSize, insertSpaces: options.insertSpaces, eol: model.getEOL() };
			const edits = remove ? removeProperty(text, path, formatting) : setProperty(text, path, value, formatting);
			if (!edits.length) {
				return textResult('No change.');
			}
			model.pushStackElement();
			model.pushEditOperations([], edits.map(edit => ({
				range: Range.fromPositions(model.getPositionAt(edit.offset), model.getPositionAt(edit.offset + edit.length)),
				text: edit.content,
			})), () => null);
			model.pushStackElement();
		} finally {
			reference.dispose();
		}
		return textResult(`Edited ${file} (unsaved; the engineer can undo it with Ctrl+Z and saves it).`);
	}
}

/** The file of `kind`'s results, relative to the project. */
export function resultFile(kind: ResultKind): string | undefined {
	const folder = (id: string) => partById(id)?.folder;
	switch (kind) {
		case 'design': return `${folder('fem')}/${FEM_RESULTS_FOLDER}/${DESIGN_SUMMARY_FILE}`;
		case 'fem': return `${folder('fem')}/${FEM_RESULTS_FOLDER}/${FEM_RESULTS_MANIFEST}`;
		case 'substructure': return `${folder('substructure')}/${SUBSTRUCTURE_SUMMARY_FILE}`;
		case 'mep': return `${folder('mep')}/${MEP_SUMMARY_FILE}`;
		case 'boq': return `${folder('boq')}/${partById('boq')?.mainFile}`;
	}
}

function textResult(text: string): MCP.CallToolResult {
	return { content: [{ type: 'text', text }] };
}

function jsonResult(value: unknown): MCP.CallToolResult {
	return textResult(JSON.stringify(value, undefined, 1));
}

function errorResult(text: string): MCP.CallToolResult {
	return { content: [{ type: 'text', text }], isError: true };
}

/** The window's JPEG capture as PNG, scaled to at most SCREENSHOT_WIDTH wide; base64. */
async function toPng(jpeg: VSBuffer): Promise<string> {
	const bitmap = await createImageBitmap(new Blob([jpeg.buffer.slice()], { type: 'image/jpeg' }));
	try {
		const scale = Math.min(1, SCREENSHOT_WIDTH / bitmap.width);
		const width = Math.round(bitmap.width * scale);
		const height = Math.round(bitmap.height * scale);
		const canvas = new OffscreenCanvas(width, height);
		canvas.getContext('2d')!.drawImage(bitmap, 0, 0, width, height);
		const png = await canvas.convertToBlob({ type: 'image/png' });
		return encodeBase64(VSBuffer.wrap(new Uint8Array(await png.arrayBuffer())));
	} finally {
		bitmap.close();
	}
}
