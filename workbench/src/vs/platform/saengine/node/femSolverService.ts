/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as cp from 'child_process';
import { createInterface } from 'readline';
import type { MessageConnection } from 'vscode-jsonrpc/node.js';
import { Emitter } from '../../../base/common/event.js';
import { Disposable, toDisposable } from '../../../base/common/lifecycle.js';
import { promises as fs } from 'fs';
import { FileAccess } from '../../../base/common/network.js';
import { dirname, extname, isAbsolute, join } from '../../../base/common/path.js';
import { isWindows } from '../../../base/common/platform.js';
import { killTree } from '../../../base/node/processes.js';
import { generateUuid } from '../../../base/common/uuid.js';
import { localize } from '../../../nls.js';
import { ILogService } from '../../log/common/log.js';
import { FemRunEvent, IFemBackendInfo, IFemCaseResults, IFemProjectValidation, IFemResultList, IFemResultView, IFemRunEventMessage, IBuildingIfc, IBuildingIfcRequest, IFemDerivation, IFemDeriveRequest, IGeneratedBuilding, ILibraryProblem, LibraryFileKind, IFemRunExit, IFemRunRequest, IFemSolverService, IStructureEdit, IStructureGeometry, IStructureScriptResult, StructureGeometryResult, IBoqComputation, IBoqComputeRequest, IReportBuild, ISoilBearing, ISoilBearingRequest, ISoilImport, ISoilSources, ISoilTemplate, ISubstructureMigration, IMepServiceParams, MepServiceMethod, ICadOpenRequest, ICadOpenResult, ProjectPlatformMethod, EngineMethod, IQgisOpenRequest, IQgisOpenResult } from '../common/femSolver.js';

interface IRun {
	readonly child: cp.ChildProcess;
	cancelled: boolean;
}

interface IBackend {
	readonly child: cp.ChildProcess;
	readonly connection: MessageConnection;
	/** Last lines the backend wrote to stderr, attached to request failures. */
	readonly stderr: string[];
}

function pythonEnv(): NodeJS.ProcessEnv {
	// Unbuffered UTF-8 so protocol lines arrive as they are written, whatever the console code page.
	return { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' };
}

export class FemSolverService extends Disposable implements IFemSolverService {

	declare readonly _serviceBrand: undefined;

	private readonly _onDidRunEvent = this._register(new Emitter<IFemRunEventMessage>());
	readonly onDidRunEvent = this._onDidRunEvent.event;

	private readonly _onDidRunExit = this._register(new Emitter<IFemRunExit>());
	readonly onDidRunExit = this._onDidRunExit.event;

	private readonly runs = new Map<string, IRun>();
	private readonly backends = new Map<string, Promise<IBackend>>();

	constructor(@ILogService private readonly logService: ILogService) {
		super();
		this._register(toDisposable(() => {
			for (const run of this.runs.values()) {
				this.kill(run.child);
			}
			for (const backend of this.backends.values()) {
				backend.then(b => { b.connection.dispose(); this.kill(b.child); }, () => { });
			}
		}));
	}

	async startRun(request: IFemRunRequest): Promise<string> {
		const runId = generateUuid();
		const args = [
			'-u', '-m', 'opensees_studio.run',
			'--project', request.project,
			'--cases', ...request.caseIds.map(String),
			'--out', request.outDir,
		];
		this.logService.info(`[saengine] starting analysis run ${runId}: ${request.python} ${args.join(' ')}`);
		const child = cp.spawn(request.python, args, { cwd: dirname(request.project), env: pythonEnv(), windowsHide: true });
		const run: IRun = { child, cancelled: false };
		this.runs.set(runId, run);

		const fire = (event: FemRunEvent) => this._onDidRunEvent.fire({ runId, event });

		createInterface({ input: child.stdout! }).on('line', line => {
			if (!line.trim()) {
				return;
			}
			try {
				fire(JSON.parse(line));
			} catch {
				// The CLI keeps stdout for the protocol; treat anything else as plain output.
				fire({ type: 'stderr', text: line });
			}
		});
		createInterface({ input: child.stderr! }).on('line', text => fire({ type: 'stderr', text }));

		let exited = false;
		const exit = (exitCode: number | null) => {
			if (exited) {
				return;
			}
			exited = true;
			this.runs.delete(runId);
			this._onDidRunExit.fire({ runId, exitCode, cancelled: run.cancelled });
		};
		child.on('error', error => {
			fire({ type: 'error', message: localize('femSolver.pythonStartFailed', "Could not start Python ({0}): {1}", request.python, error.message) });
			exit(null);
		});
		child.on('close', code => exit(code));

		return runId;
	}

	async cancelRun(runId: string): Promise<void> {
		const run = this.runs.get(runId);
		if (run) {
			run.cancelled = true;
			this.kill(run.child);
		}
	}

	getBackendInfo(python: string): Promise<IFemBackendInfo> {
		return this.request(python, 'saengine/info', {});
	}

	validateProject(python: string, project: string): Promise<IFemProjectValidation> {
		return this.request(python, 'project/validate', { path: project });
	}

	async getResultTables(python: string, outDir: string, project: string): Promise<readonly IFemCaseResults[]> {
		const result = await this.request<{ cases: IFemCaseResults[] }>(python, 'results/tables', { outDir, projectPath: project });
		return result.cases;
	}

	getResultList(python: string, outDir: string, project: string): Promise<IFemResultList> {
		return this.request(python, 'results/list', { outDir, projectPath: project });
	}

	getResultView(python: string, outDir: string, project: string, key: string, mode?: number): Promise<IFemResultView> {
		return this.request(python, 'results/view', { outDir, projectPath: project, key, mode });
	}

	async checkLibrary(python: string, kind: LibraryFileKind, text: string, companionText?: string, projectRoot?: string): Promise<readonly ILibraryProblem[]> {
		// `projectRoot`: the settings' code pack may be one of the project's own (02 Project Settings/code-packs).
		const result = await this.request<{ problems: ILibraryProblem[] }>(python, 'library/check', { kind, text, materialsText: companionText, projectRoot });
		return result.problems;
	}

	// `projectRoot` (here and in the soil requests below): the settings' code pack may be one of the project's own.
	generateBuilding(python: string, floorPlanText: string, bimText: string | undefined, projectRoot?: string): Promise<IGeneratedBuilding> {
		return this.request(python, 'bim/generate', { floorPlanText, bimText, projectRoot });
	}

	generateBuildingFromStructure(python: string, structureText: string, bimText: string | undefined, projectRoot?: string): Promise<IGeneratedBuilding> {
		return this.request(python, 'bim/generateFromStructure', { structureText, bimText, projectRoot });
	}

	buildingIfc(python: string, request: IBuildingIfcRequest): Promise<IBuildingIfc> {
		return this.request(python, 'bim/ifc', request);
	}

	deriveFem(python: string, request: IFemDeriveRequest): Promise<IFemDerivation> {
		return this.request(python, 'fem/derive', request);
	}

	shapeGeometry(python: string, shape: object): Promise<StructureGeometryResult> {
		return this.request(python, 'structure/shapeGeometry', { shape });
	}

	importGeometry(python: string, path: string, options: object, objectsText: string | undefined): Promise<StructureGeometryResult> {
		return this.request(python, 'structure/importGeometry', { path, options, objectsText });
	}

	insertGeometry(python: string, structureText: string, geometry: IStructureGeometry): Promise<IStructureEdit> {
		return this.request(python, 'structure/insert', { structureText, geometry });
	}

	runStructureScript(python: string, structureText: string, scriptPath: string): Promise<IStructureScriptResult> {
		return this.request(python, 'structure/runScript', { structureText, scriptPath });
	}

	getDesignReport(python: string, outDir: string, project: string): Promise<object> {
		return this.request(python, 'design/report', { outDir, projectPath: project });
	}

	computeBoq(python: string, request: IBoqComputeRequest): Promise<IBoqComputation> {
		return this.request(python, 'boq/compute', request);
	}

	buildReport(python: string, projectRoot: string, outPdf?: string): Promise<IReportBuild> {
		return this.request(python, 'report/build', { projectRoot, outPdf });
	}

	soilReport(python: string, soilText: string, settingsText?: string, projectRoot?: string): Promise<object> {
		return this.request(python, 'soil/report', { soilText, settingsText, projectRoot });
	}

	soilAllowableBearing(python: string, request: ISoilBearingRequest): Promise<ISoilBearing> {
		return this.request(python, 'soil/allowableBearing', request);
	}

	importSoil(python: string, path: string, soilText?: string): Promise<ISoilImport> {
		return this.request(python, 'soil/import', { path, soilText });
	}

	soilTemplate(python: string, path: string): Promise<ISoilTemplate> {
		return this.request(python, 'soil/template', { path });
	}

	soilSources(python: string, soilText: string | undefined, settingsText: string | undefined, projectRoot?: string): Promise<ISoilSources> {
		return this.request(python, 'soil/sources', { soilText, settingsText, projectRoot });
	}

	substructureReport(python: string, projectRoot: string): Promise<object> {
		return this.request(python, 'substructure/report', { projectRoot });
	}

	substructureSize(python: string, projectRoot: string, columns?: readonly string[]): Promise<object> {
		return this.request(python, 'substructure/size', { projectRoot, columns });
	}

	substructureMigrate(python: string, projectRoot: string): Promise<object> {
		return this.request(python, 'substructure/migrate', { projectRoot });
	}

	substructureEnsure(python: string, projectRoot: string): Promise<ISubstructureMigration> {
		return this.request(python, 'substructure/ensure', { projectRoot });
	}

	ssiCompare(python: string, projectRoot: string): Promise<object> {
		return this.request(python, 'fem/ssiCompare', { projectRoot });
	}

	meshCheck(python: string, projectRoot: string): Promise<object> {
		return this.request(python, 'fem/meshCheck', { projectRoot });
	}

	mepReport(python: string, projectRoot: string, mepText?: string): Promise<object> {
		return this.request(python, 'mep/report', { projectRoot, mepText });
	}

	mepSuggestSleeves(python: string, projectRoot: string, mepText?: string, allowance?: number): Promise<object> {
		return this.request(python, 'mep/suggestSleeves', { projectRoot, mepText, allowance });
	}

	mepImportIfc(python: string, projectRoot: string, path: string): Promise<object> {
		return this.request(python, 'mep/importIfc', { projectRoot, path });
	}

	plumbingReport(python: string, projectRoot: string, mepText?: string): Promise<object> {
		return this.request(python, 'mep/plumbingReport', { projectRoot, mepText });
	}

	plumbingSizeTanks(python: string, projectRoot: string, mepText?: string): Promise<object> {
		return this.request(python, 'mep/plumbingSizeTanks', { projectRoot, mepText });
	}

	plumbingSleeves(python: string, projectRoot: string, mepText?: string): Promise<object> {
		return this.request(python, 'mep/plumbingSleeves', { projectRoot, mepText });
	}

	plumbingOccupancies(python: string): Promise<object> {
		return this.request(python, 'mep/plumbingOccupancies', {});
	}

	mepService(python: string, method: MepServiceMethod, params: IMepServiceParams): Promise<object> {
		return this.request(python, method, params);
	}

	projectPlatform(python: string, method: ProjectPlatformMethod, params: object): Promise<object> {
		return this.request(python, method, params);
	}

	async openInCad(request: ICadOpenRequest): Promise<ICadOpenResult> {
		const path = request.path;
		const refuse = (problem: string): ICadOpenResult => ({ ok: false, program: null, args: [], problems: [problem] });
		if (typeof path !== 'string' || !isAbsolute(path) || extname(path).toLowerCase() !== '.dxf') {
			return refuse(localize('cad.notDxf', "Only a DXF drawing (an absolute path ending in .dxf) can be opened in CAD."));
		}
		if (!await isFile(path)) {
			return refuse(localize('cad.missing', "{0} does not exist.", path));
		}
		const found = await findCadProgram(request.program);
		if (!found) {
			// No LibreCAD: the caller hands the file to the system's DXF program.
			return { ok: true, program: null, args: [path] };
		}
		const args = [path];
		if (request.dryRun) {
			return { ok: true, program: found.program, args, source: found.source };
		}
		this.logService.info(`[saengine] opening ${path} in ${found.program}`);
		// Started directly (no shell): the drawing's path is one argument, whatever it contains.
		const child = cp.spawn(found.program, args, { cwd: dirname(path), detached: true, stdio: 'ignore', shell: false, windowsHide: false });
		return new Promise<ICadOpenResult>(resolve => {
			child.once('error', error => resolve(refuse(localize('cad.startFailed', "{0} could not be started: {1}", found.program, error.message))));
			child.once('spawn', () => {
				child.unref();
				resolve({ ok: true, program: found.program, args, source: found.source, pid: child.pid });
			});
		});
	}

	engine(python: string, method: EngineMethod, params: object): Promise<unknown> {
		return this.request(python, method, params);
	}

	async openInQgis(python: string, request: IQgisOpenRequest): Promise<IQgisOpenResult> {
		const path = request.path;
		const refuse = (problem: string): IQgisOpenResult => ({ ok: false, program: null, args: [], problems: [problem] });
		if (typeof path !== 'string' || !isAbsolute(path) || !['.gpkg', '.geojson', '.json'].includes(extname(path).toLowerCase())) {
			return refuse(localize('qgis.notGis', "Only a GeoPackage or GeoJSON file (an absolute path ending in .gpkg, .geojson or .json) can be opened in QGIS."));
		}
		if (!await isFile(path)) {
			return refuse(localize('qgis.missing', "{0} does not exist.", path));
		}
		// The program comes from this machine's setting or from the backend's search of the
		// installs (registry, Program Files, OSGeo4W): never from the project.
		const configured = request.program?.trim();
		let program: string | null = configured && isAbsolute(configured) && await isFile(configured) ? configured : null;
		if (!program) {
			const found = await this.request<string | null>(python, 'soil/qgisProgram', {});
			program = typeof found === 'string' && isAbsolute(found) && await isFile(found) ? found : null;
		}
		if (!program) {
			return { ok: true, program: null, args: [] };
		}
		const command = await this.request<string[] | { problems?: string[] }>(python, 'soil/qgisCommand', { program, filePath: path });
		if (!Array.isArray(command) || !command.length) {
			return { ok: false, program, args: [], problems: Array.isArray(command) ? [] : command.problems ?? [] };
		}
		// A .bat launcher runs through cmd.exe: the system's own (never one found on the path or
		// in the working folder), its last argument the line the backend quoted, passed verbatim.
		const viaCmd = command[0].toLowerCase() === 'cmd.exe';
		const executable = viaCmd ? (process.env['ComSpec'] && isAbsolute(process.env['ComSpec']) ? process.env['ComSpec'] : join(process.env['SystemRoot'] ?? 'C:\\Windows', 'System32', 'cmd.exe')) : command[0];
		if (!viaCmd && executable !== program) {
			return refuse(localize('qgis.unexpected', "The backend named another program than {0}.", program));
		}
		const args = command.slice(1);
		if (request.dryRun) {
			return { ok: true, program, args };
		}
		this.logService.info(`[saengine] opening ${path} in ${program}`);
		const child = cp.spawn(executable, args, { cwd: dirname(program), detached: true, stdio: 'ignore', shell: false, windowsHide: false, windowsVerbatimArguments: viaCmd });
		return new Promise<IQgisOpenResult>(resolve => {
			child.once('error', error => resolve(refuse(localize('qgis.startFailed', "{0} could not be started: {1}", program, error.message))));
			child.once('spawn', () => {
				child.unref();
				resolve({ ok: true, program, args, pid: child.pid });
			});
		});
	}

	private async request<T>(python: string, method: string, params: object): Promise<T> {
		const backend = await this.backend(python);
		try {
			return await backend.connection.sendRequest<T>(method, params);
		} catch (error) {
			const detail = backend.stderr.length ? `\n${backend.stderr.join('\n')}` : '';
			throw new Error(`${error instanceof Error ? error.message : String(error)}${detail}`);
		}
	}

	private backend(python: string): Promise<IBackend> {
		let backend = this.backends.get(python);
		if (!backend) {
			backend = this.startBackend(python);
			this.backends.set(python, backend);
			backend.catch(() => this.backends.delete(python));
		}
		return backend;
	}

	private async startBackend(python: string): Promise<IBackend> {
		const { createMessageConnection, StreamMessageReader, StreamMessageWriter } = await import('vscode-jsonrpc/node.js');
		return new Promise<IBackend>((resolve, reject) => {
			this.logService.info(`[saengine] starting backend: ${python} -m saengine.rpc`);
			const child = cp.spawn(python, ['-u', '-m', 'saengine.rpc'], { env: pythonEnv(), windowsHide: true });
			const stderr: string[] = [];
			createInterface({ input: child.stderr! }).on('line', line => {
				stderr.push(line);
				if (stderr.length > 50) {
					stderr.shift();
				}
				this.logService.trace(`[saengine backend] ${line}`);
			});

			const connection = createMessageConnection(new StreamMessageReader(child.stdout!), new StreamMessageWriter(child.stdin!));
			connection.listen();

			child.on('error', error => {
				connection.dispose();
				this.backends.delete(python);
				reject(new Error(localize('femSolver.pythonStartFailed', "Could not start Python ({0}): {1}", python, error.message)));
			});
			child.on('spawn', () => resolve({ child, connection, stderr }));
			child.on('close', code => {
				this.logService.info(`[saengine] backend exited with code ${code}`);
				connection.dispose();
				this.backends.delete(python);
				if (code !== 0 && stderr.length) {
					this.logService.error(`[saengine] backend stderr:\n${stderr.join('\n')}`);
				}
			});
		});
	}

	private kill(child: cp.ChildProcess): void {
		if (child.pid !== undefined && child.exitCode === null) {
			// The CLI may run ARPACK cases in a child Python process; take the whole tree down.
			killTree(child.pid, true).catch(() => child.kill());
		}
	}
}

async function isFile(path: string): Promise<boolean> {
	try {
		return (await fs.stat(path)).isFile();
	} catch {
		return false;
	}
}

/**
 * The LibreCAD to open drawings with: the `saengine.cad.program` setting when it names an
 * existing program, else the copy bundled with SAEngine (`resources/librecad`, beside the bundled
 * Python), else an installed LibreCAD (`%ProgramFiles%\LibreCAD`).
 */
async function findCadProgram(configured: string | undefined): Promise<{ readonly program: string; readonly source: 'setting' | 'bundled' | 'installed' } | undefined> {
	if (configured?.trim() && isAbsolute(configured.trim()) && await isFile(configured.trim())) {
		return { program: configured.trim(), source: 'setting' };
	}
	const exe = isWindows ? 'LibreCAD.exe' : 'librecad';
	const appRoot = dirname(FileAccess.asFileUri('').fsPath);
	const bundled = join(appRoot, '..', 'librecad', exe);
	if (await isFile(bundled)) {
		return { program: bundled, source: 'bundled' };
	}
	const installed = isWindows
		? [process.env['ProgramFiles'], process.env['ProgramW6432'], process.env['ProgramFiles(x86)']].filter((p): p is string => !!p).map(p => join(p, 'LibreCAD', exe))
		: ['/usr/bin/librecad', '/usr/local/bin/librecad'];
	for (const candidate of installed) {
		if (await isFile(candidate)) {
			return { program: candidate, source: 'installed' };
		}
	}
	return undefined;
}
