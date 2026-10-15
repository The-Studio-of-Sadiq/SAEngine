/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as cp from 'child_process';
import { createInterface } from 'readline';
import type { MessageConnection } from 'vscode-jsonrpc/node.js';
import { Emitter } from '../../../base/common/event.js';
import { Disposable, toDisposable } from '../../../base/common/lifecycle.js';
import { dirname } from '../../../base/common/path.js';
import { killTree } from '../../../base/node/processes.js';
import { generateUuid } from '../../../base/common/uuid.js';
import { localize } from '../../../nls.js';
import { ILogService } from '../../log/common/log.js';
import { FemRunEvent, IFemBackendInfo, IFemCaseResults, IFemProjectValidation, IFemRunEventMessage, IBuildingIfc, IBuildingIfcRequest, IFemDerivation, IFemDeriveRequest, IGeneratedBuilding, ILibraryProblem, LibraryFileKind, IFemRunExit, IFemRunRequest, IFemSolverService } from '../common/femSolver.js';

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

	async checkLibrary(python: string, kind: LibraryFileKind, text: string, companionText?: string): Promise<readonly ILibraryProblem[]> {
		const result = await this.request<{ problems: ILibraryProblem[] }>(python, 'library/check', { kind, text, materialsText: companionText });
		return result.problems;
	}

	generateBuilding(python: string, floorPlanText: string, bimText: string | undefined): Promise<IGeneratedBuilding> {
		return this.request(python, 'bim/generate', { floorPlanText, bimText });
	}

	buildingIfc(python: string, request: IBuildingIfcRequest): Promise<IBuildingIfc> {
		return this.request(python, 'bim/ifc', request);
	}

	deriveFem(python: string, request: IFemDeriveRequest): Promise<IFemDerivation> {
		return this.request(python, 'fem/derive', request);
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
