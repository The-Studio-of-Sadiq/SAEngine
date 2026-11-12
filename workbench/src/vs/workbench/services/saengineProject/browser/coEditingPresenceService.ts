/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { ResourceMap } from '../../../../base/common/map.js';
import { URI } from '../../../../base/common/uri.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { ICoEditingColleague, ISaengineCoEditingPresenceService } from '../common/coEditingPresence.js';

export class SaengineCoEditingPresenceService extends Disposable implements ISaengineCoEditingPresenceService {

	declare readonly _serviceBrand: undefined;

	private readonly parts = new ResourceMap<readonly ICoEditingColleague[]>();

	private readonly _onDidChange = this._register(new Emitter<URI>());
	readonly onDidChange = this._onDidChange.event;

	colleagues(resource: URI): readonly ICoEditingColleague[] {
		return this.parts.get(resource) ?? [];
	}

	setColleagues(resource: URI, colleagues: readonly ICoEditingColleague[]): void {
		const before = this.parts.get(resource) ?? [];
		if (JSON.stringify(before) === JSON.stringify(colleagues)) {
			return;
		}
		if (colleagues.length) {
			this.parts.set(resource, colleagues);
		} else {
			this.parts.delete(resource);
		}
		this._onDidChange.fire(resource);
	}
}

registerSingleton(ISaengineCoEditingPresenceService, SaengineCoEditingPresenceService, InstantiationType.Delayed);
