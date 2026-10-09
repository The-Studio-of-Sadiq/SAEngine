const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');
const vscode = require('vscode');

const API_VERSION = 'v1';
const REQUEST_TIMEOUT_MS = 5000;
const STRUCTURE_VIEW_TYPE = 'saengine.structure3d';
const PROJECT_FOLDERS = [
	'1. Soil Test',
	'2. Materials editor',
	'3. Object Editor',
	'4. AutoCAD',
	'5. BIM Editor',
	'6. MEP Editor',
	'7. FEA Engine',
	'8. Substructure analysis',
	'9. BOQ Generator',
];
const PROJECT_METADATA_FOLDER = '7. FEA Engine';
const MODULE_FILES = {
	soil: '1. Soil Test/site-survey.json',
	materials: '2. Materials editor/materials.json',
	objects: '3. Object Editor/objects.json',
	autocad: '4. AutoCAD/module.json',
	bim: '5. BIM Editor/module.json',
	mep: '6. MEP Editor/module.json',
	construction: '7. FEA Engine/model.json',
	substructure: '8. Substructure analysis/module.json',
	costing: '9. BOQ Generator/module.json',
};
let saengineOutput;
let structurePanel;
let workbenchPanel;
let currentProjectFile;
let currentProjectDirectory;
let projectRootWatcher;
let projectWriteQueue = Promise.resolve();

function projectMetadataPath(projectDirectory, projectName) {
	return path.join(projectDirectory, PROJECT_METADATA_FOLDER, `${projectName}.saengine`);
}

function isProjectRootOrChild(targetPath, projectDirectory) {
	const target = path.resolve(targetPath);
	const root = path.resolve(projectDirectory);
	const normalize = value => process.platform === 'win32' ? value.toLowerCase() : value;
	if (normalize(target) === normalize(root)) {
		return true;
	}
	return normalize(path.dirname(target)) === normalize(root);
}

function isWithinProject(targetPath, projectDirectory) {
	const relative = path.relative(path.resolve(projectDirectory), path.resolve(targetPath));
	return !relative || (relative !== '..' && !relative.startsWith(`..${path.sep}`)
		&& !path.isAbsolute(relative));
}

function normalizeProjectPath(value) {
	const resolved = path.resolve(value);
	return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
}

function protectProjectRootMutations(context) {
	const rejectRootMutation = (event, targets) => {
		if (!currentProjectDirectory || !targets.some(target =>
			isProjectRootOrChild(target.fsPath, currentProjectDirectory),
		)) {
			return;
		}
		const message = 'The project root is fixed. Add or change files inside one of its nine folders.';
		event.waitUntil(Promise.reject(new Error(message)));
	};

	context.subscriptions.push(
		vscode.workspace.onWillCreateFiles(event => {
			rejectRootMutation(event, event.files);
		}),
		vscode.workspace.onWillDeleteFiles(event => {
			rejectRootMutation(event, event.files);
		}),
		vscode.workspace.onWillRenameFiles(event => {
			rejectRootMutation(event, event.files.flatMap(file => [file.oldUri, file.newUri]));
		}),
		vscode.workspace.onDidDeleteFiles(event => {
			restoreDeletedProjectFolders(event.files.map(file => file.fsPath));
		}),
	);
}

function hasProjectStructure(projectDirectory) {
	if (!projectDirectory) {
		return false;
	}
	if (path.basename(projectDirectory).toLowerCase() === 'saengine projects') {
		return true;
	}
	return PROJECT_FOLDERS.some(folder => fs.existsSync(path.join(projectDirectory, folder)))
		|| fs.existsSync(path.join(projectDirectory, PROJECT_METADATA_FOLDER));
}

function watchProjectRoot(projectDirectory, context) {
	projectRootWatcher?.close();
	projectRootWatcher = undefined;
	if (!projectDirectory) {
		return;
	}
	const root = path.resolve(projectDirectory);
	let repairScheduled = false;
	let watcher;
	try {
		watcher = fs.watch(root, () => {
			if (repairScheduled) {
				return;
			}
			repairScheduled = true;
			setTimeout(() => {
				repairScheduled = false;
				void ensureProjectFolders(root).catch(error => {
					outputFor().appendLine(`Could not restore the fixed project folders: ${error.message}`);
				});
			}, 50);
		});
		watcher.on('error', error => {
			outputFor().appendLine(`Project folder watcher failed: ${error.message}`);
		});
	} catch (error) {
		outputFor().appendLine(`Could not watch the fixed project folders: ${error.message}`);
		return;
	}
	projectRootWatcher = watcher;
	context.subscriptions.push({ dispose: () => watcher.close() });
}

function setCurrentProjectDirectory(projectDirectory, context) {
	if (currentProjectDirectory && projectDirectory
		&& normalizeProjectPath(currentProjectDirectory) === normalizeProjectPath(projectDirectory)) {
		return;
	}
	currentProjectDirectory = projectDirectory;
	watchProjectRoot(projectDirectory, context);
}

function restoreDeletedProjectFolders(paths) {
	if (!currentProjectDirectory) {
		return;
	}
	const root = path.resolve(currentProjectDirectory);
	const deletedRequiredFolders = paths.filter(targetPath =>
		normalizeProjectPath(path.dirname(targetPath)) === normalizeProjectPath(root)
		&& PROJECT_FOLDERS.some(folder =>
			folder.toLowerCase() === path.basename(targetPath).toLowerCase(),
		),
	);
	if (deletedRequiredFolders.length) {
		void Promise.all(deletedRequiredFolders.map(folder =>
			fs.promises.mkdir(folder, { recursive: true }),
		)).catch(error => {
			outputFor().appendLine(`Could not restore a required project folder: ${error.message}`);
			void vscode.window.showErrorMessage(`SAEngine could not restore a required project folder: ${error.message}`);
		});
	}
}

function ensureProjectFileIsInModule(targetPath, moduleFolder) {
	if (!currentProjectDirectory) {
		throw new Error('Create or open a project before exporting files.');
	}
	const moduleRoot = path.resolve(currentProjectDirectory, moduleFolder);
	const target = path.resolve(targetPath);
	const relative = path.relative(moduleRoot, target);
	if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
		throw new Error(`Save this file inside the "${moduleFolder}" project folder.`);
	}
}

function requestJson(serviceUrl, endpointPath, method, payload) {
	return new Promise((resolve, reject) => {
		let endpoint;
		try {
			endpoint = new URL(endpointPath, serviceUrl);
		} catch (error) {
			reject(new Error(`Invalid SAEngine service URL: ${error.message}`));
			return;
		}

		const transport = endpoint.protocol === 'https:' ? https : http;
		if (endpoint.protocol !== 'http:' && endpoint.protocol !== 'https:') {
			reject(new Error(`Unsupported SAEngine service URL protocol: ${endpoint.protocol}`));
			return;
		}

		const body = payload === undefined ? undefined : JSON.stringify(payload);
		const request = transport.request(endpoint, {
			method,
			headers: body === undefined ? {} : {
				'Content-Type': 'application/json',
				'Content-Length': Buffer.byteLength(body),
			},
		}, response => {
			let body = '';
			response.setEncoding('utf8');
			response.on('data', chunk => { body += chunk; });
			response.on('end', () => {
				try {
					const result = JSON.parse(body);
					if (response.statusCode !== 200) {
						throw new Error(result.error || `SAEngine service returned HTTP ${response.statusCode}.`);
					}
					resolve(result);
				} catch (error) {
					reject(error);
				}
			});
		});

		request.setTimeout(REQUEST_TIMEOUT_MS, () => {
			request.destroy(new Error(`SAEngine service did not respond within ${REQUEST_TIMEOUT_MS} ms.`));
		});
		request.on('error', reject);
		if (body !== undefined) {
			request.write(body);
		}
		request.end();
	});
}

function currentProjectDocument() {
	const editor = vscode.window.activeTextEditor;
	if (!editor || path.extname(editor.document.fileName).toLowerCase() !== '.saengine') {
		throw new Error('Open a .saengine project file in the active editor first.');
	}
	const project = JSON.parse(editor.document.getText());
	if (!project.grids || !project.stories) {
		throw new Error('The project must define grids and stories.');
	}
	return { editor, project };
}

function currentFrameProject() {
	const { project } = currentProjectDocument();
	if (!project.frame_model || !Array.isArray(project.frame_model.load_cases)) {
		throw new Error('The project does not contain a frame model.');
	}
	return project.frame_model;
}

function replaceProjectDocument(editor, project) {
	if (project.settings && typeof project.settings === 'object') {
		project.settings.modified_at = Date.now() / 1000;
	}
	const text = editor.document.getText();
	const range = new vscode.Range(
		editor.document.positionAt(0),
		editor.document.positionAt(text.length),
	);
	return editor.edit(editBuilder => {
		editBuilder.replace(range, JSON.stringify(project, null, 2));
	});
}

async function requestPositiveNumber(prompt) {
	const value = await vscode.window.showInputBox({
		prompt,
		validateInput: text => {
			const number = Number(text);
			return Number.isFinite(number) && number > 0
				? undefined
				: 'Enter a finite number greater than zero.';
		},
	});
	return value === undefined ? undefined : Number(value);
}

async function requestNumber(prompt) {
	const value = await vscode.window.showInputBox({
		prompt,
		value: '0',
		validateInput: text => Number.isFinite(Number(text))
			? undefined
			: 'Enter a finite number.',
	});
	return value === undefined ? undefined : Number(value);
}

function openWelcomeScreen(context) {
	const logoUri = vscode.Uri.joinPath(context.extensionUri, 'media', 'saengine-mark.svg');
	const webviewRoot = vscode.Uri.joinPath(context.extensionUri, 'media');
	const panel = vscode.window.createWebviewPanel(
		'saengine.welcome',
		'SAEngine Workbench',
		vscode.ViewColumn.One,
		{
			enableScripts: true,
			localResourceRoots: [webviewRoot],
		},
	);
	workbenchPanel = panel;
	context.subscriptions.push(panel);
	panel.onDidDispose(() => {
		if (workbenchPanel === panel) {
			workbenchPanel = undefined;
		}
	}, null, context.subscriptions);
	const nonce = Array.from({ length: 32 }, () =>
		'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'.charAt(
			Math.floor(Math.random() * 62),
		),
	).join('');
	const scriptUri = panel.webview.asWebviewUri(
		vscode.Uri.joinPath(webviewRoot, 'workbench.js'),
	);
	panel.webview.html = fs.readFileSync(
		path.join(context.extensionPath, 'welcome.html'),
		'utf8',
	)
		.replace("img-src 'self'", `img-src ${panel.webview.cspSource}`)
		.replace('media/saengine-mark.svg', panel.webview.asWebviewUri(logoUri).toString())
		.replace('{{SCRIPT_URI}}', scriptUri.toString())
		.replace('{{NONCE}}', nonce);

	panel.webview.onDidReceiveMessage(async message => {
		try {
			switch (message?.command) {
				case 'ready':
					if (!await loadWorkspaceProject(context)) {
						currentProject = makeNewProject('Preview Building');
					}
					postProjectToViews(currentProject, panel);
					break;
				case 'createProject':
					await createProject(context, panel);
					break;
				case 'openProject':
					await openProject(context, panel);
					break;
				case 'previewProject': {
					const project = currentProject || currentProjectDocument().project;
					postProjectToViews(project, panel);
					break;
				}
				case 'saveProject':
					await saveWorkbenchProject(message.project, panel);
					break;
				case 'importSoil':
					await importSoilReport(panel);
					break;
				case 'exportSoil':
					await exportSoilReport(message.project);
					break;
				case 'importMaterials':
					await importMaterials(panel);
					break;
				case 'exportMaterials':
					await exportMaterials(message.project);
					break;
				case 'generateBuilding':
					await generateWorkbenchFrame(message.project, panel);
					break;
				case 'analyzeFrame':
					await analyzeWorkbenchFrame(message.project, panel);
					break;
				case 'show3DViewer':
					await show3DPreview(context);
					break;
				case 'openModuleFile':
					await openModuleFile(message.module);
					break;
			}
		} catch (error) {
			reportWorkbenchError(panel, error);
		}
	});
	return panel;
}

function postProjectToViews(project, panel) {
	panel?.webview.postMessage({
		command: 'project',
		project,
		editable: Boolean(currentProjectFile),
	});
	if (structurePanel !== panel) {
		structurePanel?.webview.postMessage({
			command: 'project',
			project,
			editable: Boolean(currentProjectFile),
		});
	}
}

async function ensureProjectFolders(projectDirectory) {
	await Promise.all(PROJECT_FOLDERS.map(folder =>
		fs.promises.mkdir(path.join(projectDirectory, folder), { recursive: true }),
	));
}

async function moveLegacyProjectFile(projectFile, projectDirectory) {
	const target = path.join(projectDirectory, PROJECT_METADATA_FOLDER, path.basename(projectFile));
	if (path.resolve(projectFile) !== path.resolve(target)) {
		try {
			await fs.promises.access(target);
			throw new Error(`A project file already exists at "${target}".`);
		} catch (error) {
			if (error.code !== 'ENOENT') {
				throw error;
			}
		}
		await fs.promises.rename(projectFile, target);
	}
	return target;
}

function projectModuleDocuments(project) {
	return new Map([
		[MODULE_FILES.soil, project.soil_site || {}],
		[MODULE_FILES.materials, {
			materials: project.frame_model?.materials || [],
			sections: project.frame_model?.sections || [],
		}],
		[MODULE_FILES.objects, {
			members: project.frame_model?.members || [],
			joints: project.frame_model?.joints || [],
			object_properties: project.object_properties || {},
			surface_objects: project.surface_objects || [],
		}],
		[MODULE_FILES.construction, {
			construction_mode: project.construction_mode || 'building',
			grids: project.grids,
			stories: project.stories,
			frame_model: project.frame_model,
			analysis_results: project.analysis_results,
		}],
		...Object.entries(MODULE_FILES)
			.filter(([module]) => !['soil', 'materials', 'objects', 'construction'].includes(module))
			.map(([module, file]) => [file, {
				module,
				status: 'planned',
				description: 'Reserved project module; implementation is planned.',
			}]),
	]);
}

async function writeModuleFiles(project, projectDirectory) {
	const documents = projectModuleDocuments(project);
	await Promise.all([...documents.entries()].map(async ([relativePath, data]) => {
		const target = path.join(projectDirectory, relativePath);
		await fs.promises.mkdir(path.dirname(target), { recursive: true });
		await fs.promises.writeFile(target, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
	}));
}

async function openModuleFile(module) {
	const relativePath = MODULE_FILES[module];
	if (!relativePath) {
		throw new Error('Select a valid project module before opening its data file.');
	}
	if (!currentProjectFile) {
		throw new Error('Create or open a project to access its module data files.');
	}
	const document = await vscode.workspace.openTextDocument(
		vscode.Uri.file(path.join(currentProjectDirectory, relativePath)),
	);
	await vscode.window.showTextDocument(document, vscode.ViewColumn.One);
}

function reportWorkbenchError(panel, error) {
	const text = error instanceof Error ? error.message : String(error);
	outputFor().appendLine(`SAEngine workbench: ${text}`);
	panel.webview.postMessage({ command: 'operationError', message: text });
	void vscode.window.showErrorMessage(`SAEngine: ${text}`);
}

async function saveWorkbenchProject(project, panel) {
	if (!currentProjectFile) {
		throw new Error('Create or open a project before saving changes.');
	}
	if (!project || typeof project !== 'object' || !project.settings || !project.frame_model) {
		throw new Error('The workbench sent an invalid project document.');
	}
	project.settings.modified_at = Date.now() / 1000;
	await writeProjectFile(project);
	currentProject = project;
	panel.webview.postMessage({ command: 'saved' });
	if (structurePanel !== panel) {
		structurePanel?.webview.postMessage({ command: 'project', project });
	}
}

async function writeProjectFile(project) {
	const projectFile = currentProjectFile;
	if (!projectFile) {
		throw new Error('No SAEngine project file is open.');
	}
	const content = `${JSON.stringify(project, null, 2)}\n`;
	const pendingWrite = projectWriteQueue.catch(() => {}).then(() =>
		Promise.all([
			fs.promises.writeFile(projectFile, content, 'utf8'),
			writeModuleFiles(project, currentProjectDirectory),
		]),
	);
	projectWriteQueue = pendingWrite;
	await pendingWrite;
}

function csvCell(value) {
	let text = value === null || value === undefined ? '' : String(value);
	if (/^[\s]*[=+\-@]/.test(text)) {
		text = `'${text}`;
	}
	return `"${text.replace(/"/g, '""')}"`;
}

function csvRows(text, delimiter = ',') {
	const rows = [];
	let row = [];
	let cell = '';
	let quoted = false;
	for (let index = 0; index < text.length; index++) {
		const character = text[index];
		if (quoted) {
			if (character === '"' && text[index + 1] === '"') {
				cell += '"';
				index++;
			} else if (character === '"') {
				quoted = false;
			} else {
				cell += character;
			}
		} else if (character === '"' && cell.length === 0) {
			quoted = true;
		} else if (character === delimiter) {
			row.push(cell);
			cell = '';
		} else if (character === '\n' || character === '\r') {
			if (character === '\r' && text[index + 1] === '\n') {
				index++;
			}
			row.push(cell);
			if (row.some(value => value.length)) {
				rows.push(row);
			}
			row = [];
			cell = '';
		} else {
			cell += character;
		}
	}
	row.push(cell);
	if (row.some(value => value.length)) {
		rows.push(row);
	}
	if (quoted) {
		throw new Error('The CSV report contains an unclosed quoted field.');
	}
	return rows;
}

function inferSoilFields(text, tabular) {
	const fields = {};
	const aliases = new Map([
		['site name', 'site_name'], ['project name', 'site_name'], ['site', 'site_name'],
		['location', 'location'], ['address', 'location'], ['site address', 'location'],
		['latitude', 'latitude'], ['lat', 'latitude'],
		['longitude', 'longitude'], ['lon', 'longitude'], ['long', 'longitude'],
		['length', 'length_m'], ['length m', 'length_m'],
		['width', 'width_m'], ['width m', 'width_m'],
		['area', 'area_m2'], ['area m2', 'area_m2'],
		['soil classification', 'soil_class'], ['soil class', 'soil_class'],
		['allowable bearing', 'allowable_bearing_kpa'], ['allowable bearing pressure', 'allowable_bearing_kpa'],
		['allowable bearing kpa', 'allowable_bearing_kpa'],
		['groundwater depth', 'groundwater_depth_m'], ['groundwater depth m', 'groundwater_depth_m'],
		['notes', 'notes'], ['survey notes', 'notes'],
	]);
	if (tabular) {
		const firstLine = text.split(/\r?\n/, 1)[0] || '';
		const delimiter = firstLine.includes('\t') ? '\t' : ',';
		const rows = csvRows(text, delimiter);
		if (rows.length > 1) {
			for (const [index, heading] of rows[0].entries()) {
				const normalizedHeading = heading.trim().replace(/^\uFEFF/, '').toLowerCase().replace(/[_-]+/g, ' ');
				const key = aliases.get(normalizedHeading);
				const value = rows[1][index]?.trim();
				if (key && value) {
					const numeric = Number.parseFloat(value);
					fields[key] = ['latitude', 'longitude', 'length_m', 'width_m', 'area_m2', 'allowable_bearing_kpa', 'groundwater_depth_m'].includes(key)
						? (Number.isFinite(numeric) ? numeric : value)
						: value;
				}
			}
		}
	}
	for (const line of text.split(/\r?\n/)) {
		const match = /^\s*([^:：]+)\s*[:：]\s*(.*?)\s*$/.exec(line);
		if (!match) {
			continue;
		}
		const key = aliases.get(match[1].trim().toLowerCase().replace(/[_-]+/g, ' '));
		if (key && match[2]) {
			const numeric = Number.parseFloat(match[2]);
			fields[key] = ['latitude', 'longitude', 'length_m', 'width_m', 'area_m2', 'allowable_bearing_kpa', 'groundwater_depth_m'].includes(key)
				? (Number.isFinite(numeric) ? numeric : match[2])
				: match[2];
		}
	}
	return fields;
}

function xmlText(value) {
	return value
		.replace(/<[^>]*>/g, '')
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&quot;/g, '"')
		.replace(/&apos;/g, "'")
		.replace(/&amp;/g, '&')
		.trim();
}

function readZipEntries(buffer) {
	let endRecord = -1;
	for (let offset = Math.max(0, buffer.length - 65557); offset <= buffer.length - 22; offset++) {
		if (buffer.readUInt32LE(offset) === 0x06054b50) {
			endRecord = offset;
		}
	}
	if (endRecord < 0) {
		throw new Error('The selected file is not a valid Office Open XML document.');
	}
	const entryCount = buffer.readUInt16LE(endRecord + 10);
	let cursor = buffer.readUInt32LE(endRecord + 16);
	const entries = new Map();
	for (let index = 0; index < entryCount; index++) {
		if (buffer.readUInt32LE(cursor) !== 0x02014b50) {
			throw new Error('The Office document has a malformed ZIP directory.');
		}
		const method = buffer.readUInt16LE(cursor + 10);
		const compressedSize = buffer.readUInt32LE(cursor + 20);
		const nameLength = buffer.readUInt16LE(cursor + 28);
		const extraLength = buffer.readUInt16LE(cursor + 30);
		const commentLength = buffer.readUInt16LE(cursor + 32);
		const localOffset = buffer.readUInt32LE(cursor + 42);
		const name = buffer.toString('utf8', cursor + 46, cursor + 46 + nameLength);
		if (compressedSize > 32 * 1024 * 1024 || localOffset + 30 > buffer.length) {
			throw new Error('The Office document contains an oversized or invalid entry.');
		}
		const localNameLength = buffer.readUInt16LE(localOffset + 26);
		const localExtraLength = buffer.readUInt16LE(localOffset + 28);
		const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
		const compressed = buffer.subarray(dataOffset, dataOffset + compressedSize);
		const content = method === 0
			? compressed
			: method === 8
				? zlib.inflateRawSync(compressed, { maxOutputLength: 32 * 1024 * 1024 })
				: undefined;
		if (!content) {
			throw new Error(`Unsupported compression method in Office entry "${name}".`);
		}
		entries.set(name, content.toString('utf8'));
		cursor += 46 + nameLength + extraLength + commentLength;
	}
	return entries;
}

function extractXlsxText(entries) {
	const shared = entries.get('xl/sharedStrings.xml') || '';
	const sharedStrings = [...shared.matchAll(/<si\b[^>]*>([\s\S]*?)<\/si>/g)]
		.map(([, item]) => [...item.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)]
			.map(([, text]) => xmlText(text)).join(''));
	const sheet = entries.get('xl/worksheets/sheet1.xml');
	if (!sheet) {
		throw new Error('The workbook does not contain a first worksheet.');
	}
	return [...sheet.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)].map(([, row]) =>
		[...row.matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>/g)].map(([, attributes, body]) => {
			const type = /\bt="([^"]+)"/.exec(attributes)?.[1];
			const value = /<v\b[^>]*>([\s\S]*?)<\/v>/.exec(body)?.[1] || '';
			if (type === 's') {
				return sharedStrings[Number(value)] || '';
			}
			if (type === 'inlineStr') {
				return [...body.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)]
					.map(([, text]) => xmlText(text)).join('');
			}
			return xmlText(value);
		}).join('\t'),
	).join('\n');
}

function extractDocxText(entries) {
	const document = entries.get('word/document.xml');
	if (!document) {
		throw new Error('The Word document does not contain document text.');
	}
	return [...document.matchAll(/<w:p\b[^>]*>([\s\S]*?)<\/w:p>/g)]
		.map(([, paragraph]) => [...paragraph.matchAll(/<w:t\b[^>]*>([\s\S]*?)<\/w:t>/g)]
			.map(([, text]) => xmlText(text)).join(''))
		.filter(Boolean)
		.join('\n');
}

async function chooseReportFile(title, filters) {
	return vscode.window.showOpenDialog({
		title,
		canSelectFiles: true,
		canSelectFolders: false,
		canSelectMany: false,
		filters,
	});
}

async function importSoilReport(panel) {
	const files = await chooseReportFile('Import soil report text or spreadsheet', {
		'Supported reports': ['csv', 'xlsx', 'docx', 'txt', 'json'],
	});
	if (!files?.length) {
		return;
	}
	const file = files[0].fsPath;
	const extension = path.extname(file).toLowerCase();
	const data = await fs.promises.readFile(file);
	if (data.byteLength > 20 * 1024 * 1024) {
		throw new Error('Soil report imports are limited to 20 MB.');
	}
	let text;
	if (extension === '.xlsx' || extension === '.docx') {
		const entries = readZipEntries(data);
		text = extension === '.xlsx' ? extractXlsxText(entries) : extractDocxText(entries);
	} else {
		text = data.toString('utf8');
	}
	panel.webview.postMessage({
		command: 'soilImported',
		fileName: path.basename(file),
		text: text.slice(0, 2_000_000),
		truncated: text.length > 2_000_000,
		fields: inferSoilFields(text, extension === '.csv' || extension === '.xlsx'),
	});
	void vscode.window.showInformationMessage(`Extracted report text from ${path.basename(file)}.`);
}

async function exportSoilReport(project) {
	const soil = project?.soil_site;
	if (!soil || typeof soil !== 'object') {
		throw new Error('There is no soil survey data to export.');
	}
	if (!currentProjectFile) {
		throw new Error('Create or open a project before exporting its survey.');
	}
	const destination = await vscode.window.showSaveDialog({
		title: 'Export soil site survey',
		saveLabel: 'Export Survey CSV',
		defaultUri: vscode.Uri.file(path.join(currentProjectDirectory, PROJECT_FOLDERS[0], 'soil-site-survey.csv')),
		filters: { 'CSV spreadsheet': ['csv'] },
	});
	if (!destination) {
		return;
	}
	ensureProjectFileIsInModule(destination.fsPath, PROJECT_FOLDERS[0]);
	const fields = [
		['Site name', soil.site_name, ''],
		['Location / address', soil.location, ''],
		['Latitude', soil.latitude, 'decimal degrees'],
		['Longitude', soil.longitude, 'decimal degrees'],
		['Site length', soil.length_m, 'm'],
		['Site width', soil.width_m, 'm'],
		['Site area', soil.area_m2, 'm²'],
		['Soil classification', soil.soil_class, ''],
		['Allowable bearing pressure', soil.allowable_bearing_kpa, 'kPa'],
		['Groundwater depth', soil.groundwater_depth_m, 'm'],
		['Survey notes', soil.notes, ''],
		['Imported source report', soil.imported_file, ''],
	];
	const csv = [['Property', 'Value', 'Unit'], ...fields].map(row => row.map(csvCell).join(',')).join('\r\n');
	await fs.promises.writeFile(destination.fsPath, `\uFEFF${csv}\r\n`, 'utf8');
	void vscode.window.showInformationMessage(`Exported soil survey to ${destination.fsPath}.`);
}

async function importMaterials(panel) {
	const files = await chooseReportFile('Import SAEngine material and section library', {
		'JSON material library': ['json'],
	});
	if (!files?.length) {
		return;
	}
	const data = JSON.parse(await fs.promises.readFile(files[0].fsPath, 'utf8'));
	const materials = Array.isArray(data) ? data : data.materials;
	const sections = Array.isArray(data.sections) ? data.sections : [];
	if (!Array.isArray(materials) || materials.some(item =>
		!item || typeof item !== 'object' || !Number.isSafeInteger(Number(item.id)) || Number(item.id) < 1,
	)) {
		throw new Error('Import JSON must contain a materials array with numeric IDs.');
	}
	if (sections.some(item =>
		!item || typeof item !== 'object' || !Number.isSafeInteger(Number(item.id)) || Number(item.id) < 1,
	)) {
		throw new Error('Every imported section must have a numeric ID.');
	}
	for (const [items, label] of [[materials, 'material'], [sections, 'section']]) {
		const ids = items.map(item => Number(item.id));
		if (new Set(ids).size !== ids.length) {
			throw new Error(`Imported ${label} IDs must be unique.`);
		}
	}
	const normalizeProperties = (items, keys) => items.map(item => {
		const normalized = { ...item, id: Number(item.id) };
		for (const key of keys) {
			if (normalized[key] !== undefined && normalized[key] !== null && normalized[key] !== '') {
				const value = Number(normalized[key]);
				if (!Number.isFinite(value)) {
					throw new Error(`Material library property "${key}" must be numeric.`);
				}
				normalized[key] = value;
			}
		}
		return normalized;
	});
	panel.webview.postMessage({
		command: 'materialsImported',
		materials: normalizeProperties(materials, [
			'elastic_modulus', 'shear_modulus', 'density', 'yield_strength',
		]),
		sections: normalizeProperties(sections, [
			'area', 'torsion_constant', 'moment_of_inertia_y', 'moment_of_inertia_z',
		]),
	});
}

async function exportMaterials(project) {
	const frame = project?.frame_model;
	if (!frame || !Array.isArray(frame.materials) || !Array.isArray(frame.sections)) {
		throw new Error('There is no material library to export.');
	}
	if (!currentProjectFile) {
		throw new Error('Create or open a project before exporting its material library.');
	}
	const destination = await vscode.window.showSaveDialog({
		title: 'Export materials and sections',
		saveLabel: 'Export JSON',
		defaultUri: vscode.Uri.file(path.join(currentProjectDirectory, PROJECT_FOLDERS[1], 'materials.json')),
		filters: { 'JSON file': ['json'] },
	});
	if (!destination) {
		return;
	}
	ensureProjectFileIsInModule(destination.fsPath, PROJECT_FOLDERS[1]);
	await fs.promises.writeFile(destination.fsPath, `${JSON.stringify({
		materials: frame.materials,
		sections: frame.sections,
	}, null, 2)}\n`, 'utf8');
	void vscode.window.showInformationMessage(`Exported material library to ${destination.fsPath}.`);
}

async function persistGeneratedProject(project, panel) {
	if (!currentProjectFile) {
		throw new Error('Create or open a project before generating a model.');
	}
	project.settings.modified_at = Date.now() / 1000;
	await writeProjectFile(project);
	currentProject = project;
	postProjectToViews(project, panel);
}

async function generateWorkbenchFrame(project, panel) {
	if (project?.frame_model?.members?.length) {
		const replace = await vscode.window.showWarningMessage(
			'Generating a grid frame replaces the current frame members, nodes, and load cases.',
			'Replace model',
			'Cancel',
		);
		if (replace !== 'Replace model') {
			return;
		}
	}
	const material = project?.frame_model?.materials?.[0];
	const section = project?.frame_model?.sections?.[0];
	if (!material || !section) {
		throw new Error('Add a material and section in Materials before generating the frame.');
	}
	if (!Number.isSafeInteger(Number(material.id)) || Number(material.id) < 1
		|| !Number.isSafeInteger(Number(section.id)) || Number(section.id) < 1) {
		throw new Error('The active material and section must have positive integer IDs.');
	}
	for (const [name, value] of Object.entries({
		'elastic modulus': material.elastic_modulus,
		'shear modulus': material.shear_modulus,
		'section area': section.area,
		'torsion constant': section.torsion_constant,
		'moment of inertia Iy': section.moment_of_inertia_y,
		'moment of inertia Iz': section.moment_of_inertia_z,
	})) {
		if (!Number.isFinite(Number(value)) || Number(value) <= 0) {
			throw new Error(`Enter a finite positive ${name} in Materials before generating the frame.`);
		}
	}
	const serviceUrl = vscode.workspace.getConfiguration('saengine').get('serviceUrl');
	const frameModel = await requestJson(
		serviceUrl,
		`/api/${API_VERSION}/models/grid-frame`,
		'POST',
		{ project, material, section },
	);
	const materialId = Number(material.id);
	const sectionId = Number(section.id);
	frameModel.materials = [
		{ ...material, ...frameModel.materials[0], id: materialId },
		...project.frame_model.materials.filter(item => Number(item.id) !== materialId),
	];
	frameModel.sections = [
		{ ...section, ...frameModel.sections[0], id: sectionId },
		...project.frame_model.sections.filter(item => Number(item.id) !== sectionId),
	];
	frameModel.members = frameModel.members.map(member => ({
		...member,
		material_id: materialId,
		section_id: sectionId,
	}));
	project.frame_model = frameModel;
	delete project.analysis_results;
	await persistGeneratedProject(project, panel);
	void vscode.window.showInformationMessage(
		`Generated a frame with ${frameModel.joints.length} joints and ${frameModel.members.length} members.`,
	);
}

async function analyzeWorkbenchFrame(project, panel) {
	const frame = project?.frame_model;
	if (!frame?.members?.length || !frame?.load_cases?.length) {
		throw new Error('Add frame members and a load case before analysis.');
	}
	const loadCase = frame.load_cases.find(item => item.joint_loads?.length);
	if (!loadCase) {
		throw new Error('Add at least one joint load before analysis.');
	}
	const serviceUrl = vscode.workspace.getConfiguration('saengine').get('serviceUrl');
	const results = await requestJson(
		serviceUrl,
		`/api/${API_VERSION}/analysis/linear-static`,
		'POST',
		{ model: frame, load_case_id: loadCase.id },
	);
	project.analysis_results = results;
	await persistGeneratedProject(project, panel);
	const maxTranslation = results.displacements.reduce((maximum, item) =>
		Math.max(maximum, Math.hypot(...item.values.slice(0, 3))), 0);
	void vscode.window.showInformationMessage(
		`Linear-static analysis completed. Maximum joint translation: ${maxTranslation.toPrecision(5)} m.`,
	);
}

function outputFor() {
	return saengineOutput;
}

let currentProject;

function makeNewProject(name) {
	const now = Date.now() / 1000;
	const gridLine = (label, position) => ({
		id: require('node:crypto').randomUUID(),
		label,
		position,
		is_visible: true,
	});
	const stories = [{ name: 'Base', elevation: 0, height: 0, is_base: true }];
	for (let level = 1; level <= 4; level++) {
		stories.push({
			name: level === 4 ? 'Roof' : `Story ${level}`,
			elevation: level * 3,
			height: 3,
			is_base: false,
		});
	}
	return {
		saengine_version: '0.1.0',
		settings: {
			project_name: name,
			author: '',
			description: '',
			created_at: now,
			modified_at: now,
		},
		units: { active_system: 'SI (kN, m, kg)' },
		grids: {
			x_grids: [0, 6, 12, 18].map((position, index) =>
				gridLine(String(index + 1), position),
			),
			y_grids: [0, 6, 12].map((position, index) =>
				gridLine(String.fromCharCode(65 + index), position),
			),
		},
		stories: {
			stories: stories.map(story => ({
				id: require('node:crypto').randomUUID(),
				is_master: true,
				color: '#4FC3F7',
				...story,
			})),
		},
		soil_site: {},
		construction_mode: 'building',
		object_properties: {},
		surface_objects: [],
		frame_model: {
			model_version: 1,
			joints: [],
			members: [],
			materials: [],
			sections: [],
			load_cases: [],
		},
	};
}

async function activateProjectFolder(folderPath) {
	const folderUri = vscode.Uri.file(folderPath);
	const folders = vscode.workspace.workspaceFolders || [];
	if (folders.length === 1 && folders[0].uri.fsPath === folderUri.fsPath) {
		return;
	}
	if (!vscode.workspace.updateWorkspaceFolders(0, folders.length, { uri: folderUri })) {
		throw new Error(`Could not open project folder: ${folderPath}`);
	}
}

async function createProject(context, panel) {
	const name = await vscode.window.showInputBox({
		title: 'New SAEngine Project',
		prompt: 'Enter a name for the structural project',
		value: 'My Building',
		validateInput: value => {
			const trimmed = value.trim();
			return trimmed && !/[<>:"/\\|?*\x00-\x1f]/.test(trimmed)
				? undefined
				: 'Enter a project name without Windows path characters.';
		},
	});
	if (name === undefined) {
		return;
	}

	const defaultFolder = path.join(os.homedir(), 'Documents', 'SAEngine Projects');
	await fs.promises.mkdir(defaultFolder, { recursive: true });
	const selectedFolders = await vscode.window.showOpenDialog({
		title: 'Choose where to save the project',
		openLabel: 'Create Project Here',
		canSelectFiles: false,
		canSelectFolders: true,
		canSelectMany: false,
		defaultUri: vscode.Uri.file(defaultFolder),
	});
	if (!selectedFolders?.length) {
		return;
	}
	if (currentProjectDirectory && isWithinProject(selectedFolders[0].fsPath, currentProjectDirectory)) {
		throw new Error('Create another project outside the current project folder structure.');
	}

	const projectDirectory = path.join(selectedFolders[0].fsPath, name.trim());
	const projectFile = projectMetadataPath(projectDirectory, name.trim());
	await fs.promises.mkdir(projectDirectory, { recursive: false });
	await ensureProjectFolders(projectDirectory);
	const project = makeNewProject(name.trim());
	await fs.promises.writeFile(projectFile, `${JSON.stringify(project, null, 2)}\n`, {
		flag: 'wx',
	});
	await writeModuleFiles(project, projectDirectory);
	await activateProjectFolder(projectDirectory);
	setCurrentProjectDirectory(projectDirectory, context);
	currentProjectFile = projectFile;
	currentProject = project;
	postProjectToViews(project, panel);
	outputFor().appendLine(`Created project: ${projectFile}`);
	void vscode.window.showInformationMessage(`Created SAEngine project "${name.trim()}".`);
}

async function readProject(projectUri) {
	const text = await vscode.workspace.fs.readFile(projectUri);
	const project = JSON.parse(Buffer.from(text).toString('utf8'));
	if (!project.settings || !project.grids || !project.stories) {
		throw new Error('The selected file is not a valid SAEngine project.');
	}
	project.frame_model ||= {
		model_version: 1,
		joints: [],
		members: [],
		materials: [],
		sections: [],
		load_cases: [],
	};
	project.soil_site ||= {};
	project.construction_mode ||= 'building';
	project.object_properties ||= {};
	project.surface_objects ||= [];
	return project;
}

async function openProject(context, panel) {
	const files = await vscode.window.showOpenDialog({
		title: 'Open SAEngine Project',
		openLabel: 'Open Project',
		canSelectFiles: true,
		canSelectFolders: false,
		canSelectMany: false,
		filters: { 'SAEngine Projects': ['saengine'] },
	});
	if (!files?.length) {
		return;
	}
	const project = await readProject(files[0]);
	const selectedFile = files[0].fsPath;
	const selectedDirectory = path.dirname(selectedFile);
	const selectedFolder = path.basename(selectedDirectory).toLowerCase();
	const projectDirectory = selectedFolder === PROJECT_METADATA_FOLDER.toLowerCase()
		|| PROJECT_FOLDERS.some(folder => folder.toLowerCase() === selectedFolder)
		? path.dirname(selectedDirectory)
		: selectedDirectory;
	await ensureProjectFolders(projectDirectory);
	await writeModuleFiles(project, projectDirectory);
	const projectFile = await moveLegacyProjectFile(selectedFile, projectDirectory);
	await activateProjectFolder(projectDirectory);
	setCurrentProjectDirectory(projectDirectory, context);
	currentProjectFile = projectFile;
	currentProject = project;
	postProjectToViews(project, panel);
	outputFor().appendLine(`Opened project: ${projectFile}`);
	void vscode.window.showInformationMessage(
		`Opened SAEngine project "${project.settings.project_name || path.basename(files[0].fsPath)}".`,
	);
}

async function loadWorkspaceProject(context) {
	const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
	if (!folder) {
		return false;
	}
	if (path.basename(folder).toLowerCase() === 'saengine projects') {
		await ensureProjectFolders(folder);
	}
	const rootEntries = await fs.promises.readdir(folder, { withFileTypes: true });
	const metadataDirectory = path.join(folder, PROJECT_METADATA_FOLDER);
	const hasMetadataDirectory = rootEntries.some(entry =>
		entry.isDirectory() && entry.name === PROJECT_METADATA_FOLDER,
	);
	const moduleEntries = hasMetadataDirectory
		? await fs.promises.readdir(metadataDirectory, { withFileTypes: true })
		: [];
	const candidates = [
		...rootEntries
			.filter(entry => entry.isFile() && path.extname(entry.name).toLowerCase() === '.saengine')
			.map(entry => path.join(folder, entry.name)),
		...moduleEntries
			.filter(entry => entry.isFile() && path.extname(entry.name).toLowerCase() === '.saengine')
			.map(entry => path.join(metadataDirectory, entry.name)),
	];
	if (candidates.length > 1) {
		throw new Error('This folder contains more than one SAEngine project file. Keep one project file in the project structure.');
	}
	if (candidates.length === 0) {
		return false;
	}
	const projectUri = vscode.Uri.file(candidates[0]);
	currentProject = await readProject(projectUri);
	await ensureProjectFolders(folder);
	setCurrentProjectDirectory(folder, context);
	currentProjectFile = await moveLegacyProjectFile(projectUri.fsPath, folder);
	await writeModuleFiles(currentProject, folder);
	return true;
}

function structurePanelHtml(webview, context) {
	const webviewRoot = vscode.Uri.joinPath(context.extensionUri, 'media');
	const nonce = Array.from({ length: 32 }, () =>
		'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'.charAt(
			Math.floor(Math.random() * 62),
		),
	).join('');
	const scriptUri = webview.asWebviewUri(
		vscode.Uri.joinPath(webviewRoot, 'workbench.js'),
	);
	return fs.readFileSync(path.join(context.extensionPath, 'structure.html'), 'utf8')
		.replace('{{SCRIPT_URI}}', scriptUri.toString())
		.replace('{{NONCE}}', nonce);
}

async function sendInitialProject(panel, context) {
	if (!currentProject && !await loadWorkspaceProject(context)) {
		currentProject = makeNewProject('Preview Building');
	}
	panel.webview.postMessage({
		command: 'project',
		project: currentProject,
		editable: Boolean(currentProjectFile),
	});
}

function configureStructurePanel(panel, context) {
	structurePanel = panel;
	panel.webview.options = {
		enableScripts: true,
		localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')],
	};
	panel.webview.html = structurePanelHtml(panel.webview, context);
	panel.onDidDispose(() => {
		if (structurePanel === panel) {
			structurePanel = undefined;
		}
	}, null, context.subscriptions);
	panel.webview.onDidReceiveMessage(async message => {
		if (message?.command !== 'ready') {
			return;
		}
		try {
			await sendInitialProject(panel, context);
		} catch (error) {
			const text = `Could not load the SAEngine project for the 3D view: ${error.message}`;
			outputFor().appendLine(text);
			void vscode.window.showErrorMessage(text);
		}
	}, null, context.subscriptions);
}

async function show3DPreview(context) {
	if (structurePanel) {
		structurePanel.reveal(vscode.ViewColumn.Two);
		return;
	}
	const panel = vscode.window.createWebviewPanel(
		STRUCTURE_VIEW_TYPE,
		'3D Structure',
		vscode.ViewColumn.Two,
		{ enableScripts: true, retainContextWhenHidden: true },
	);
	configureStructurePanel(panel, context);
}

function activate(context) {
	saengineOutput = vscode.window.createOutputChannel('SAEngine');
	context.subscriptions.push(saengineOutput);
	const activeWorkspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
	if (hasProjectStructure(activeWorkspace)) {
		setCurrentProjectDirectory(activeWorkspace, context);
		void ensureProjectFolders(activeWorkspace).catch(error => {
			outputFor().appendLine(`Could not restore the fixed project folders: ${error.message}`);
		});
	}
	context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(() => {
		const workspaceRoot = vscode.workspace.workspaceFolders
			?.map(folder => folder.uri.fsPath)
			.find(hasProjectStructure);
		if (workspaceRoot !== currentProjectDirectory) {
			setCurrentProjectDirectory(workspaceRoot, context);
			if (workspaceRoot) {
				void ensureProjectFolders(workspaceRoot).catch(error => {
					outputFor().appendLine(`Could not restore the fixed project folders: ${error.message}`);
				});
			}
		}
	}));
	protectProjectRootMutations(context);
	const output = saengineOutput;
	context.subscriptions.push(vscode.window.registerWebviewPanelSerializer(
		STRUCTURE_VIEW_TYPE,
		{
			async deserializeWebviewPanel(panel) {
				configureStructurePanel(panel, context);
				panel.reveal(vscode.ViewColumn.Two, true);
			},
		},
	));
	context.subscriptions.push(
		vscode.commands.registerCommand('saengine.openWelcome', () => openWelcomeScreen(context)),
		vscode.commands.registerCommand('saengine.createProject', () =>
			createProject(context, openWelcomeScreen(context)),
		),
		vscode.commands.registerCommand('saengine.openProject', () =>
			openProject(context, openWelcomeScreen(context)),
		),
		vscode.commands.registerCommand('saengine.show3DPreview', async () => {
			try {
				await show3DPreview(context);
			} catch (error) {
				void vscode.window.showErrorMessage(`SAEngine: ${error.message}`);
			}
		}),
	);
	const welcomePanel = openWelcomeScreen(context);
	void show3DPreview(context).catch(error => {
		const text = `Could not open the SAEngine 3D view: ${error.message}`;
		output.appendLine(text);
		void vscode.window.showErrorMessage(text);
	});
	context.subscriptions.push(vscode.commands.registerCommand('saengine.checkService', async () => {
		const serviceUrl = vscode.workspace.getConfiguration('saengine').get('serviceUrl');
		try {
			const health = await requestJson(serviceUrl, `/api/${API_VERSION}/health`, 'GET');
			if (health.service !== 'saengine' || health.api_version !== API_VERSION || health.status !== 'ok') {
				throw new Error('The endpoint returned an incompatible SAEngine health response.');
			}
			const message = `Connected to SAEngine ${health.version} (${health.api_version}).`;
			output.appendLine(message);
			output.show(true);
			void vscode.window.showInformationMessage(message);
		} catch (error) {
			const message = `Could not connect to SAEngine at ${serviceUrl}: ${error.message}`;
			output.appendLine(message);
			output.show(true);
			void vscode.window.showErrorMessage(message);
		}
	}));

	context.subscriptions.push(vscode.commands.registerCommand('saengine.analyzeCurrentProject', async () => {
		try {
			const frameModel = currentFrameProject();
			if (frameModel.load_cases.length === 0) {
				throw new Error('The frame model has no load cases. Generate it again or add a load case.');
			}
			const loadCase = await vscode.window.showQuickPick(
				frameModel.load_cases.map(item => ({
					label: item.name || `Load case ${item.id}`,
					description: `ID ${item.id}`,
					id: item.id,
				})),
				{ placeHolder: 'Select a linear-static load case' },
			);
			if (!loadCase) {
				return;
			}
			const selectedCase = frameModel.load_cases.find(item => item.id === loadCase.id);
			if (!selectedCase || !selectedCase.joint_loads || selectedCase.joint_loads.length === 0) {
				throw new Error(`Load case "${loadCase.label}" has no joint loads.`);
			}

			const serviceUrl = vscode.workspace.getConfiguration('saengine').get('serviceUrl');
			const result = await requestJson(
				serviceUrl,
				`/api/${API_VERSION}/analysis/linear-static`,
				'POST',
				{ model: frameModel, load_case_id: loadCase.id },
			);
			const maxDisplacement = result.displacements.reduce((maximum, item) => {
				const translation = Math.hypot(...item.values.slice(0, 3));
				return translation > maximum.magnitude
					? { jointId: item.joint_id, magnitude: translation }
					: maximum;
			}, { jointId: undefined, magnitude: 0 });
			const message = `Linear-static analysis completed (${loadCase.label}); maximum joint translation: ${maxDisplacement.magnitude.toPrecision(5)}.`;
			output.appendLine(message);
			output.appendLine(JSON.stringify(result, null, 2));
			output.show(true);
			void vscode.window.showInformationMessage(message);
		} catch (error) {
			const message = `SAEngine analysis failed: ${error.message}`;
			output.appendLine(message);
			output.show(true);
			void vscode.window.showErrorMessage(message);
		}
	}));

	context.subscriptions.push(vscode.commands.registerCommand('saengine.generateGridFrameModel', async () => {
		try {
			const { editor, project } = currentProjectDocument();
			const proceed = await vscode.window.showInformationMessage(
				'This creates a regular frame with one material and one section shared by every beam and column. Enter all properties in SAEngine base units (kN, m).',
				'Continue',
				'Cancel',
			);
			if (proceed !== 'Continue') {
				return;
			}
			const materialPrompts = [
				['elastic_modulus', 'Elastic modulus E (kN/m²)'],
				['shear_modulus', 'Shear modulus G (kN/m²)'],
			];
			const sectionPrompts = [
				['area', 'Section area A (m²)'],
				['torsion_constant', 'Torsion constant J (m⁴)'],
				['moment_of_inertia_y', 'Moment of inertia Iy (m⁴)'],
				['moment_of_inertia_z', 'Moment of inertia Iz (m⁴)'],
			];
			const material = { name: 'Material 1' };
			const section = { name: 'Section 1' };
			for (const [key, prompt] of materialPrompts) {
				const value = await requestPositiveNumber(prompt);
				if (value === undefined) {
					return;
				}
				material[key] = value;
			}
			for (const [key, prompt] of sectionPrompts) {
				const value = await requestPositiveNumber(prompt);
				if (value === undefined) {
					return;
				}
				section[key] = value;
			}

			const serviceUrl = vscode.workspace.getConfiguration('saengine').get('serviceUrl');
			const frameModel = await requestJson(
				serviceUrl,
				`/api/${API_VERSION}/models/grid-frame`,
				'POST',
				{ project, material, section },
			);
			project.frame_model = frameModel;
			if (!await replaceProjectDocument(editor, project)) {
				throw new Error('The project editor could not be updated.');
			}
			const message = `Generated ${frameModel.joints.length} joints and ${frameModel.members.length} frame members. Save the project to keep these changes.`;
			output.appendLine(message);
			output.show(true);
			void vscode.window.showInformationMessage(message);
		} catch (error) {
			const message = `SAEngine model generation failed: ${error.message}`;
			output.appendLine(message);
			output.show(true);
			void vscode.window.showErrorMessage(message);
		}
	}));

	context.subscriptions.push(vscode.commands.registerCommand('saengine.addJointLoad', async () => {
		try {
			const { editor, project } = currentProjectDocument();
			const frameModel = project.frame_model;
			if (!frameModel || !Array.isArray(frameModel.load_cases) || frameModel.load_cases.length === 0) {
				throw new Error('Generate a grid frame model before adding loads.');
			}
			const loadCase = await vscode.window.showQuickPick(
				frameModel.load_cases.map(item => ({
					label: item.name || `Load case ${item.id}`,
					description: `ID ${item.id}`,
					id: item.id,
				})),
				{ placeHolder: 'Select a load case' },
			);
			if (!loadCase) {
				return;
			}
			const joint = await vscode.window.showQuickPick(
				frameModel.joints.map(item => ({
					label: `Joint ${item.id}`,
					description: `(${item.coordinates.join(', ')})`,
					id: item.id,
				})),
				{ placeHolder: 'Select a loaded joint' },
			);
			if (!joint) {
				return;
			}
			const loadPrompts = [
				'Force FX (kN)',
				'Force FY (kN)',
				'Force FZ (kN)',
				'Moment MX (kN·m)',
				'Moment MY (kN·m)',
				'Moment MZ (kN·m)',
			];
			const values = [];
			for (const prompt of loadPrompts) {
				const value = await requestNumber(prompt);
				if (value === undefined) {
					return;
				}
				values.push(value);
			}
			const selectedCase = frameModel.load_cases.find(item => item.id === loadCase.id);
			selectedCase.joint_loads.push({ joint_id: joint.id, values });
			if (!await replaceProjectDocument(editor, project)) {
				throw new Error('The project editor could not be updated.');
			}
			const message = `Added a joint load at joint ${joint.id}. Save the project to keep this change.`;
			output.appendLine(message);
			output.show(true);
			void vscode.window.showInformationMessage(message);
		} catch (error) {
			const message = `SAEngine load assignment failed: ${error.message}`;
			output.appendLine(message);
			output.show(true);
			void vscode.window.showErrorMessage(message);
		}
	}));
}

function deactivate() {}

module.exports = { activate, deactivate };
