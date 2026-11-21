/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEditor as CadEditorApi } from '@saengine/cad-editor';
import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { DisposableStore, IDisposable, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuItemAction, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { DraftActiveContext, registerRibbonGroupLabel, registerRibbonGroupPriority, registerRibbonItemHint, RibbonMenus } from '../../saengineRibbon/browser/ribbonRegistry.js';
import { executeActiveCadCommand, getActiveCadEditor, getActiveCadEditorPane, onDidChangeActiveCadEditor } from './activeCadEditor.js';
import { CAD_DRAFT_COMMANDS, DRAFT_RIBBON_GROUPS, DRAFT_RIBBON_SUBMENUS, DraftRibbonSubmenus, ICadDraftCommandSpec } from './cadDraftCommands.js';
import { isLightCanvas } from './cadHost.js';
import { aciToCss, pickCadLayer } from './floorPlanCadBar.js';

const CAD_CATEGORY = localize2('saengine.cad.category', "CAD");
const CAD_STANDALONE_EDITOR_ID = 'workbench.editor.saengine.cad';
const CAD_TAB_MENUS = new Set([RibbonMenus.Draft, RibbonMenus.Annotate, RibbonMenus.BlocksParametric]);

for (const group of DRAFT_RIBBON_GROUPS) {
	registerRibbonGroupLabel(group.key, group.label);
	registerRibbonGroupPriority(group.key, group.collapsePriority);
}

for (const sub of DRAFT_RIBBON_SUBMENUS) {
	MenuRegistry.appendMenuItem(sub.menuId, {
		group: sub.group,
		order: sub.order,
		submenu: sub.submenu,
		title: sub.title,
		icon: sub.icon,
		isSplitButton: true,
	});
	registerRibbonItemHint(sub.submenu.id, {
		size: sub.size,
		label: sub.title,
		primaryCommandId: sub.primaryCommandId,
	}, sub.menuId);
}

function registerCadDraftCommand(spec: ICadDraftCommandSpec): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: spec.id,
				title: spec.title,
				category: CAD_CATEGORY,
				icon: spec.icon,
				tooltip: spec.tooltip,
				metadata: { description: spec.tooltip },
				f1: true,
				precondition: DraftActiveContext,
				menu: {
					id: spec.menuId,
					group: spec.group,
					order: spec.order,
				},
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			await executeActiveCadCommand(accessor.get(IEditorService), spec.cadCommand);
		}
	});

	if (CAD_TAB_MENUS.has(spec.menuId)) {
		registerRibbonItemHint(spec.id, {
			size: spec.size ?? 'small',
			label: spec.title.value,
		}, spec.menuId);
	}
}

for (const spec of CAD_DRAFT_COMMANDS) {
	registerCadDraftCommand(spec);
}

/** Renders the live Current Layer dropdown button inside Draft -> Layers reusing FloorPlanCadBar's layer list. */
function renderCurrentLayerDropdown(
	container: HTMLElement,
	instantiationService: IInstantiationService,
	action: MenuItemAction,
): IDisposable {
	const store = new DisposableStore();
	const editorService = instantiationService.invokeFunction(a => a.get(IEditorService));
	const themeService = instantiationService.invokeFunction(a => a.get(IThemeService));
	const hoverService = instantiationService.invokeFunction(a => a.get(IHoverService));

	const button = append(container, $<HTMLButtonElement>('button.sa-ribbon-btn.sa-ribbon-btn-small.sa-ribbon-layer-select'));
	button.type = 'button';
	button.setAttribute('aria-haspopup', 'listbox');
	const swatch = append(button, $('span.sa-ribbon-layer-swatch'));
	const labelEl = append(button, $('span.sa-ribbon-layer-name', undefined, '0'));
	append(button, $(`span.sa-ribbon-layer-caret${ThemeIcon.asCSSSelector(Codicon.chevronDown)}`)).setAttribute('aria-hidden', 'true');

	const editorListeners = store.add(new MutableDisposable<DisposableStore>());
	const hover = store.add(new MutableDisposable<IDisposable>());
	let boundEditor: CadEditorApi | undefined;

	const updateDisplay = () => {
		const editor = getActiveCadEditor(editorService);
		const isLight = isLightCanvas(themeService.getColorTheme());
		if (!editor) {
			labelEl.textContent = '0';
			swatch.style.background = 'transparent';
			button.setAttribute('aria-disabled', 'true');
			button.classList.add('sa-ribbon-disabled');
			const tip = localize('cad.currentLayer.none', "Current Layer (CLAYER): No active CAD drawing");
			button.setAttribute('aria-label', tip);
			hover.value = hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip);
			return;
		}
		button.removeAttribute('aria-disabled');
		button.classList.remove('sa-ribbon-disabled');
		try {
			const currentName = editor.layers.current();
			const props = editor.properties.get();
			const layer = editor.layers.list().find(l => l.name === currentName);
			const displayName = props.layer === 'varies' ? '*VARIES*' : currentName;
			labelEl.textContent = displayName;
			swatch.style.background = layer ? aciToCss(layer.color, isLight) : 'transparent';
			const tip = localize('cad.currentLayer.tip', "Current Layer / Move Selection to Layer ({0}) — CLAYER", currentName);
			button.setAttribute('aria-label', tip);
			hover.value = hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, tip);
		} catch {
			labelEl.textContent = '0';
			swatch.style.background = 'transparent';
		}
	};

	const bindEditor = () => {
		const editor = getActiveCadEditor(editorService);
		if (editor !== boundEditor) {
			boundEditor = editor;
			const sub = new DisposableStore();
			if (editor) {
				sub.add(toDisposable(editor.layers.onDidChangeLayers(updateDisplay)));
				sub.add(toDisposable(editor.selection.onDidChangeSelection(updateDisplay)));
				sub.add(toDisposable(editor.onDidChange(updateDisplay)));
			}
			editorListeners.value = sub;
		}
		updateDisplay();
	};

	store.add(editorService.onDidActiveEditorChange(bindEditor));
	store.add(onDidChangeActiveCadEditor(bindEditor));
	store.add(themeService.onDidColorThemeChange(updateDisplay));
	store.add(addDisposableListener(button, EventType.CLICK, () => {
		if (button.getAttribute('aria-disabled') === 'true') {
			return;
		}
		void action.run();
	}));

	bindEditor();
	return store;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.cad.currentLayer',
			title: localize2('cad.cmd.currentLayer', "Current Layer"),
			category: CAD_CATEGORY,
			icon: Codicon.layersActive,
			tooltip: localize2('cad.tip.currentLayer', "Switch current drafting layer or move selected objects to a layer (CLAYER)"),
			metadata: { description: localize2('cad.meta.currentLayer', "Switch current drafting layer or move selected objects to a layer (CLAYER)") },
			f1: true,
			precondition: DraftActiveContext,
			menu: {
				id: RibbonMenus.Draft,
				group: '3_Layers',
				order: 2,
			},
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const editorService = accessor.get(IEditorService);
		const pane = getActiveCadEditorPane(editorService);
		if (pane?.showCadLayerPicker) {
			await pane.showCadLayerPicker();
			return;
		}
		const editor = getActiveCadEditor(editorService);
		if (!editor) {
			return;
		}
		await pickCadLayer(editor, accessor.get(IQuickInputService), accessor.get(INotificationService));
	}
});

registerRibbonItemHint('saengine.cad.currentLayer', {
	size: 'small',
	renderCustom: renderCurrentLayerDropdown,
}, RibbonMenus.Draft);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.cad.properties',
			title: localize2('cad.cmd.properties', "Properties"),
			category: CAD_CATEGORY,
			icon: Codicon.symbolProperty,
			tooltip: localize2('cad.tip.properties', "Open Properties palette / change object properties (PROPERTIES / CHPROP)"),
			metadata: { description: localize2('cad.meta.properties', "Open Properties palette / change object properties (PROPERTIES / CHPROP)") },
			f1: true,
			precondition: DraftActiveContext,
			menu: {
				id: RibbonMenus.Draft,
				group: '4_Properties',
				order: 3,
			},
			keybinding: {
				weight: KeybindingWeight.WorkbenchContrib,
				primary: KeyMod.CtrlCmd | KeyCode.Digit1,
				when: ActiveEditorContext.isEqualTo(CAD_STANDALONE_EDITOR_ID),
			},
		});
	}

	override run(accessor: ServicesAccessor): void {
		const pane = getActiveCadEditorPane(accessor.get(IEditorService));
		if (pane?.focusCadProperties) {
			pane.focusCadProperties();
			return;
		}
		void executeActiveCadCommand(accessor.get(IEditorService), 'CHPROP');
	}
});

registerRibbonItemHint('saengine.cad.properties', {
	size: 'small',
	label: localize('cad.label.properties', "Properties"),
}, RibbonMenus.Draft);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.cad.toggleCommandLine',
			title: localize2('cad.cmd.toggleCommandLine', "Command Line"),
			category: CAD_CATEGORY,
			icon: Codicon.terminal,
			tooltip: localize2('cad.tip.toggleCommandLine', "Show or hide the CAD command line (:)"),
			metadata: { description: localize2('cad.meta.toggleCommandLine', "Show or hide the CAD command line (:)") },
			f1: true,
			precondition: DraftActiveContext,
			menu: {
				id: DraftRibbonSubmenus.UtilView,
				group: '2_cli',
				order: 1,
			},
		});
	}

	override run(accessor: ServicesAccessor): void {
		getActiveCadEditorPane(accessor.get(IEditorService))?.toggleCadCommandLine?.();
	}
});
