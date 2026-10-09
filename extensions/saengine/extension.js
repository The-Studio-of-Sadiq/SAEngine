const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');

const API_VERSION = 'v1';
const REQUEST_TIMEOUT_MS = 5000;

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
	const panel = vscode.window.createWebviewPanel(
		'saengine.welcome',
		'SAEngine',
		vscode.ViewColumn.One,
		{
			enableScripts: false,
			localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')],
		},
	);
	context.subscriptions.push(panel);
	panel.webview.html = fs.readFileSync(
		path.join(context.extensionPath, 'welcome.html'),
		'utf8',
	).replace("img-src 'self'", `img-src ${panel.webview.cspSource}`)
		.replace('media/saengine-mark.svg', panel.webview.asWebviewUri(logoUri).toString());
}

function activate(context) {
	const output = vscode.window.createOutputChannel('SAEngine');
	context.subscriptions.push(output);
	context.subscriptions.push(
		vscode.commands.registerCommand('saengine.openWelcome', () => openWelcomeScreen(context)),
	);
	openWelcomeScreen(context);

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
