/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import * as cp from 'child_process';
import { join } from '../../../base/common/path.js';

/*
 * The Authenticode check of a program SAEngine is about to run or unpack (docs/marketplace-plan.md
 * §6, round M7): Windows' own `Get-AuthenticodeSignature` (no new dependency), which checks the
 * signature, the certificate chain and the timestamp. The publisher SAEngine expects is
 * product.json's `saengineSigning.publisher` (the certificate's subject, e.g. the SignPath
 * certificate's `CN=...`); until the owner sets it (signing is not set up yet), callers skip the
 * check and rely on the release's SHA-256 alone.
 */

export interface IAuthenticodeResult {
	/** `Valid`, `NotSigned`, `HashMismatch`, `NotTrusted`, `UnknownError`... (Windows' SignatureStatus). */
	readonly status: string;
	/** The signer certificate's subject (`CN=..., O=..., C=...`), when signed. */
	readonly subject: string;
}

/** Windows' signature status of `file` (PowerShell, path passed in the environment, no shell). */
export function authenticodeSignature(file: string, timeoutMs = 30_000): Promise<IAuthenticodeResult> {
	const script = '$s = Get-AuthenticodeSignature -LiteralPath $env:SAENGINE_SIGNED_FILE; '
		+ '[pscustomobject]@{ status = [string]$s.Status; subject = [string]$s.SignerCertificate.Subject } | ConvertTo-Json -Compress';
	const powershell = join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
	return new Promise(resolve => {
		cp.execFile(powershell, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script], {
			env: { ...process.env, SAENGINE_SIGNED_FILE: file },
			timeout: timeoutMs,
			windowsHide: true,
		}, (error, stdout) => {
			if (error) {
				resolve({ status: 'UnknownError', subject: '' });
				return;
			}
			try {
				const parsed = JSON.parse(stdout.trim()) as { status?: unknown; subject?: unknown };
				resolve({ status: typeof parsed.status === 'string' ? parsed.status : 'UnknownError', subject: typeof parsed.subject === 'string' ? parsed.subject : '' });
			} catch {
				resolve({ status: 'UnknownError', subject: '' });
			}
		});
	});
}

/**
 * Why `result` is not a valid signature by `publisher`, or undefined when it is. The publisher
 * matches the subject's common name (`CN=<publisher>`) or the whole subject, ignoring case.
 */
export function authenticodeProblem(result: IAuthenticodeResult, publisher: string): string | undefined {
	if (result.status !== 'Valid') {
		return result.status === 'NotSigned' ? 'it is not signed' : `its signature is not valid (${result.status})`;
	}
	const wanted = publisher.trim().toLowerCase();
	const subject = result.subject.toLowerCase();
	const cn = /(?:^|,\s*)cn=("?)([^,"]+)\1/.exec(subject)?.[2]?.trim();
	if (subject !== wanted && cn !== wanted && cn !== wanted.replace(/^cn=/, '')) {
		return `it is signed by ${result.subject || 'someone else'}, not by ${publisher}`;
	}
	return undefined;
}
