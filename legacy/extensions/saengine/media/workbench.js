(() => {
	const vscode = acquireVsCodeApi();
	const canvas = document.getElementById('structure-view');
	const context = canvas?.getContext('2d');
	const stats = document.getElementById('model-stats');
	const modelName = document.getElementById('model-name');
	const modulePanel = document.getElementById('module-panel');
	const modules = {
		soil: ['SOIL TEST', 'Project-root folder: 1. Soil Test. Site location, dimensions and ground characteristics. Import text/tabular reports; scanned-image OCR is deferred.'],
		materials: ['MATERIALS', 'Project material and section library. Enter verified properties before using them in analysis.'],
		objects: ['OBJECT EDITOR', 'Project-root folder: 3. Object Editor. Inspect and assign properties to frame beams and columns. Slab and wall FEM elements are not implemented yet.'],
		construction: ['CONSTRUCTION · 3D MODEL', 'Create a regular building frame or assemble a 3D node-and-member FEM model, assign loads and run linear-static analysis.'],
	};

	let project;
	let projectEditable = false;
	let activeModule = 'construction';
	let selectedMemberId;
	let selectedSurfaceId;
	let selectedMaterialId;
	let selectedSectionId;
	let yaw = -0.72;
	let pitch = 0.36;
	let zoom = 1;
	let drag;
	let animationFrame;

	function starterProject() {
		const makeGrid = (label, position) => ({
			id: `${label}-${position}`,
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
			settings: { project_name: 'Starter Building' },
			grids: {
				x_grids: [0, 6, 12, 18].map((position, index) =>
					makeGrid(String(index + 1), position),
				),
				y_grids: [0, 6, 12].map((position, index) =>
					makeGrid(String.fromCharCode(65 + index), position),
				),
			},
			stories: { stories },
			frame_model: { joints: [], members: [] },
		};
	}

	function buildGeometry(model) {
		const frame = model.frame_model;
		const surfaces = (model.surface_objects || []).map(surface => ({
			...surface,
			points: (surface.points || []).map(point => point.map(Number)),
		})).filter(surface => surface.points.length === 4
			&& surface.points.every(point => point.length === 3 && point.every(Number.isFinite)));
		const surfaceNodes = surfaces.flatMap(surface => surface.points.map(position => ({
			id: `surface-${surface.id}`,
			position,
		})));
		if (frame && frame.joints?.length && frame.members?.length) {
			const nodes = new Map(frame.joints.map(node => [node.id, {
				id: node.id,
				position: node.coordinates.map(Number),
			}]));
			const members = frame.members.map(member => ({
				start: nodes.get(member.start_joint),
				end: nodes.get(member.end_joint),
			})).filter(member => member.start && member.end);
			return { nodes: [...nodes.values(), ...surfaceNodes], members, surfaces };
		}

		const xCoordinates = (model.grids?.x_grids || [])
			.map(grid => Number(grid.position))
			.filter(Number.isFinite);
		const yCoordinates = (model.grids?.y_grids || [])
			.map(grid => Number(grid.position))
			.filter(Number.isFinite);
		const elevations = (model.stories?.stories || [])
			.map(story => Number(story.elevation))
			.filter(Number.isFinite);
		if (!xCoordinates.length || !yCoordinates.length || elevations.length < 2) {
			return { nodes: surfaceNodes, members: [], surfaces };
		}
		const levels = [...new Set(elevations)].sort((a, b) => a - b);
		const xs = [...new Set(xCoordinates)].sort((a, b) => a - b);
		const ys = [...new Set(yCoordinates)].sort((a, b) => a - b);
		const nodes = [];
		const lookup = new Map();
		for (let level = 0; level < levels.length; level++) {
			for (let iy = 0; iy < ys.length; iy++) {
				for (let ix = 0; ix < xs.length; ix++) {
					const node = {
						id: nodes.length + 1,
						position: [xs[ix], ys[iy], levels[level]],
						level,
						ix,
						iy,
					};
					nodes.push(node);
					lookup.set(`${level}:${iy}:${ix}`, node);
				}
			}
		}
		const members = [];
		function connect(a, b) {
			members.push({ start: a, end: b });
		}
		for (let level = 0; level < levels.length - 1; level++) {
			for (let iy = 0; iy < ys.length; iy++) {
				for (let ix = 0; ix < xs.length; ix++) {
					connect(lookup.get(`${level}:${iy}:${ix}`), lookup.get(`${level + 1}:${iy}:${ix}`));
				}
			}
		}
		for (let level = 1; level < levels.length; level++) {
			for (let iy = 0; iy < ys.length; iy++) {
				for (let ix = 0; ix < xs.length - 1; ix++) {
					connect(lookup.get(`${level}:${iy}:${ix}`), lookup.get(`${level}:${iy}:${ix + 1}`));
				}
			}
			for (let ix = 0; ix < xs.length; ix++) {
				for (let iy = 0; iy < ys.length - 1; iy++) {
					connect(lookup.get(`${level}:${iy}:${ix}`), lookup.get(`${level}:${iy + 1}:${ix}`));
				}
			}
		}
		return { nodes: [...nodes, ...surfaceNodes], members, surfaces, xs, ys, levels };
	}

	function escapeHtml(value) {
		return String(value ?? '').replace(/[&<>"']/g, character => ({
			'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
		})[character]);
	}

	function numberField(label, name, value, step = 'any') {
		return `<label>${label}<input type="number" name="${name}" step="${step}" value="${escapeHtml(value)}"></label>`;
	}

	function textField(label, name, value, wide = false) {
		return `<label${wide ? ' class="wide"' : ''}>${label}<input name="${name}" value="${escapeHtml(value)}"></label>`;
	}

	function ensureProjectData() {
		project.soil_site ||= {};
		project.frame_model ||= { model_version: 1, joints: [], members: [], materials: [], sections: [], load_cases: [] };
		project.frame_model.joints ||= [];
		project.frame_model.members ||= [];
		project.frame_model.materials ||= [];
		project.frame_model.sections ||= [];
		project.frame_model.load_cases ||= [];
		project.object_properties ||= {};
		project.surface_objects ||= [];
	}

	function renderSoil() {
		const soil = project.soil_site;
		return `<form data-form="soil">
			<div class="field-grid">
				${textField('Site / project name', 'site_name', soil.site_name, true)}
				${textField('Location / address', 'location', soil.location, true)}
				${numberField('Latitude', 'latitude', soil.latitude)}
				${numberField('Longitude', 'longitude', soil.longitude)}
				${numberField('Site length (m)', 'length_m', soil.length_m)}
				${numberField('Site width (m)', 'width_m', soil.width_m)}
				${numberField('Site area (m²)', 'area_m2', soil.area_m2)}
				${textField('Soil classification', 'soil_class', soil.soil_class)}
				${numberField('Allowable bearing (kPa)', 'allowable_bearing_kpa', soil.allowable_bearing_kpa)}
				${numberField('Groundwater depth (m)', 'groundwater_depth_m', soil.groundwater_depth_m)}
				<label class="wide">Survey notes<textarea name="notes">${escapeHtml(soil.notes)}</textarea></label>
			</div>
			${soil.imported_file ? `<p>Extracted from <strong>${escapeHtml(soil.imported_file)}</strong>; source text is retained${soil.imported_truncated ? ' (first 2 MB; truncated)' : ''}.</p>` : ''}
			<div class="panel-actions">
				<button class="primary" type="submit">Save soil data</button>
				<button type="button" data-action="import-soil">Import report</button>
				<button type="button" data-action="export-soil">Export survey CSV</button>
			</div>
		</form>`;
	}

	function renderMaterials() {
		const model = project.frame_model;
		const material = model.materials.find(item => item.id === selectedMaterialId) || model.materials[0] || {};
		const section = model.sections.find(item => item.id === selectedSectionId) || model.sections[0] || {};
		selectedMaterialId = material.id;
		selectedSectionId = section.id;
		const enabled = material.properties_enabled || {};
		return `<form data-form="materials">
			<div class="field-grid">
				<label>Material record<select name="material_record">${model.materials.map(item => `<option value="${item.id}"${item.id === material.id ? ' selected' : ''}>${escapeHtml(item.name || `Material ${item.id}`)}</option>`).join('')}</select></label>
				<label>Section record<select name="section_record">${model.sections.map(item => `<option value="${item.id}"${item.id === section.id ? ' selected' : ''}>${escapeHtml(item.name || `Section ${item.id}`)}</option>`).join('')}</select></label>
			</div>
			<h3>Material properties</h3>
			<div class="field-grid">
				${textField('Name', 'material_name', material.name)}
				<label>Material type<select name="material_type">
					${['Concrete', 'Structural steel', 'Timber', 'Other'].map(type => `<option${material.material_type === type ? ' selected' : ''}>${type}</option>`).join('')}
				</select></label>
				<label class="wide">Design code / standard<input name="design_code" value="${escapeHtml(material.design_code)}" placeholder="e.g. ACI 318-19, AISC 360-22"></label>
				${numberField('Elastic modulus E (kN/m²)', 'elastic_modulus', material.elastic_modulus)}
				${numberField('Shear modulus G (kN/m²)', 'shear_modulus', material.shear_modulus)}
				${numberField('Density (kg/m³)', 'density', material.density)}
				${numberField('Yield / strength (kN/m²)', 'yield_strength', material.yield_strength)}
			</div>
			<div class="check-row">
				${[['elastic_modulus', 'E'], ['shear_modulus', 'G'], ['density', 'Density'], ['yield_strength', 'Strength']].map(([key, label]) => `<label><input type="checkbox" name="enabled_${key}"${enabled[key] !== false ? ' checked' : ''}>${label}</label>`).join('')}
			</div>
			<h3>Frame section</h3>
			<div class="field-grid">
				${textField('Section name', 'section_name', section.name)}
				<label>Section type<select name="section_type">
					${['Rectangular', 'Circular', 'Wide flange', 'Custom'].map(type => `<option${section.section_type === type ? ' selected' : ''}>${type}</option>`).join('')}
				</select></label>
				${numberField('Area A (m²)', 'area', section.area)}
				${numberField('Torsion J (m⁴)', 'torsion_constant', section.torsion_constant)}
				${numberField('Moment Iy (m⁴)', 'moment_of_inertia_y', section.moment_of_inertia_y)}
				${numberField('Moment Iz (m⁴)', 'moment_of_inertia_z', section.moment_of_inertia_z)}
			</div>
			<div class="panel-actions">
				<button class="primary" type="submit">Save properties</button>
				<button type="button" data-action="add-material">Add material</button>
				<button type="button" data-action="add-section">Add section</button>
				<button type="button" data-action="import-materials">Import JSON</button>
				<button type="button" data-action="export-materials">Export JSON</button>
			</div>
			<p class="notice">Analysis uses the selected frame material and section in consistent base units (kN, m). Confirm code, units and values with the responsible engineer.</p>
		</form>`;
	}

	function renderObjects() {
		const model = project.frame_model;
		const nodes = new Map(model.joints.map(node => [node.id, node]));
		const members = model.members;
		const selected = members.find(member => member.id === selectedMemberId) || members[0];
		selectedMemberId = selected?.id;
		const detail = selected && (project.object_properties[selected.id] ||= {});
		const list = members.map(member => {
			const start = nodes.get(member.start_joint)?.coordinates || [];
			const end = nodes.get(member.end_joint)?.coordinates || [];
			const kind = detailType(member, nodes);
			return `<button type="button" class="member-row" data-member="${escapeHtml(member.id)}"><span>${kind} ${escapeHtml(member.id)}<br>${escapeHtml(member.start_joint)} → ${escapeHtml(member.end_joint)}</span><span>${start.map(Number).join(', ')} → ${end.map(Number).join(', ')}</span></button>`;
		}).join('');
		const surfaces = project.surface_objects;
		const surface = surfaces.find(item => item.id === selectedSurfaceId);
		const surfaceList = surfaces.map(item =>
			`<button type="button" class="member-row" data-surface="${escapeHtml(item.id)}"><span>${item.type === 'wall' ? 'Wall' : 'Slab'} ${escapeHtml(item.id)}</span><span>${escapeHtml(item.label || '')}</span></button>`,
		).join('');
		return `<p>${members.length} frame elements · ${model.joints.length} joints</p>
			<div class="member-list">${list || '<p>Generate a building frame in Construction to edit its members.</p>'}</div>
			<div class="panel-actions">
				<button type="button" data-action="add-slab">Add slab</button>
				<button type="button" data-action="add-wall">Add wall</button>
			</div>
			<h3>Slabs and walls · ${surfaces.length}</h3>
			<div class="member-list">${surfaceList || '<p>No surface objects yet.</p>'}</div>
			${selected ? `<form data-form="object">
				<h3>${detailType(selected, nodes)} ${selected.id}</h3>
				<div class="field-grid">
					<label>Material<select name="material_id">${model.materials.map(item => `<option value="${escapeHtml(item.id)}"${item.id === selected.material_id ? ' selected' : ''}>${escapeHtml(item.name || `Material ${item.id}`)}</option>`).join('')}</select></label>
					<label>Section<select name="section_id">${model.sections.map(item => `<option value="${escapeHtml(item.id)}"${item.id === selected.section_id ? ' selected' : ''}>${escapeHtml(item.name || `Section ${item.id}`)}</option>`).join('')}</select></label>
					${textField('Member label', 'member_label', detail.label, true)}
					${numberField('Design length (m)', 'design_length_m', detail.design_length_m)}
				</div>
				<button class="primary" type="submit">Assign member properties</button>
			</form>` : ''}
			${surface ? `<form data-form="surface">
				<h3>${surface.type === 'wall' ? 'Wall' : 'Slab'} ${surface.id}</h3>
				<div class="field-grid">${textField('Label', 'surface_label', surface.label, true)}
					${surface.points.map((point, index) => ['X', 'Y', 'Z'].map((axis, coordinate) =>
						numberField(`P${index + 1} ${axis} (m)`, `p${index}_${coordinate}`, point[coordinate]),
					).join('')).join('')}
					${numberField('Thickness (m)', 'thickness_m', surface.thickness_m)}
					<label>Material<select name="surface_material_id"><option value="">Unassigned</option>${model.materials.map(item => `<option value="${escapeHtml(item.id)}"${item.id === surface.material_id ? ' selected' : ''}>${escapeHtml(item.name || `Material ${item.id}`)}</option>`).join('')}</select></label>
				</div>
				<button class="primary" type="submit">Save surface</button>
			</form>` : ''}
			<p class="notice">Slabs and walls are editable and shown in the 3D view, but are not yet plate/shell FEM elements and are excluded from analysis.</p>`;
	}

	function detailType(member, nodes) {
		const start = nodes.get(member.start_joint)?.coordinates || [];
		const end = nodes.get(member.end_joint)?.coordinates || [];
		return Math.abs(Number(start[2]) - Number(end[2])) > 1e-9 ? 'Column' : 'Beam';
	}

	function renderConstruction() {
		const model = project.frame_model;
		const loadCase = model.load_cases[0];
		return `<label class="wide">Model workflow<select id="construction-mode">
				<option value="building"${project.construction_mode !== 'node-fem' ? ' selected' : ''}>Regular building frame · grid/story generator</option>
				<option value="node-fem"${project.construction_mode === 'node-fem' ? ' selected' : ''}>General 3D node FEM · manual nodes and members</option>
			</select></label>
			<div id="building-controls"${project.construction_mode === 'node-fem' ? ' hidden' : ''}>
				<p>${project.grids.x_grids.length} X grids · ${project.grids.y_grids.length} Y grids · ${project.stories.stories.length} levels</p>
				<button class="primary" type="button" data-action="generate-building">Generate grid frame</button>
			</div>
			<div id="fem-controls"${project.construction_mode !== 'node-fem' ? ' hidden' : ''}>
				<p>${model.joints.length} nodes · ${model.members.length} members · ${loadCase?.joint_loads?.length || 0} joint loads</p>
				<form data-form="add-node">
					<h3>Add node (m)</h3><div class="field-grid">
						${numberField('X', 'x', 0)}${numberField('Y', 'y', 0)}${numberField('Z', 'z', 0)}
					</div><label class="check-row"><input type="checkbox" name="fixed"> Fully fixed support</label>
					<button type="submit">Add node</button>
				</form>
				<form data-form="add-member">
					<h3>Add frame member</h3><div class="field-grid">
						<label>Start node<select name="start_joint">${model.joints.map(node => `<option value="${node.id}">${node.id} (${node.coordinates.join(', ')})</option>`).join('')}</select></label>
						<label>End node<select name="end_joint">${model.joints.map(node => `<option value="${node.id}">${node.id} (${node.coordinates.join(', ')})</option>`).join('')}</select></label>
					</div><button type="submit"${model.joints.length < 2 ? ' disabled' : ''}>Connect nodes</button>
				</form>
			</div>
			<form data-form="add-load">
				<h3>Add nodal load (kN, kN·m)</h3><div class="field-grid">
					<label>Node<select name="joint_id">${model.joints.map(node => `<option value="${escapeHtml(node.id)}">${escapeHtml(node.id)}</option>`).join('')}</select></label>
					${['FX', 'FY', 'FZ', 'MX', 'MY', 'MZ'].map(axis => numberField(axis, axis.toLowerCase(), 0)).join('')}
				</div><button type="submit"${!model.joints.length ? ' disabled' : ''}>Add load</button>
			</form>
			<button class="primary" type="button" data-action="analyze"${!model.members.length ? ' disabled' : ''}>Run linear-static analysis</button>
			<p class="notice">Analysis is a linear-elastic 3D frame prototype. Review geometry, restraints, loads, member properties and results independently; it is not a code-compliance design check.</p>`;
	}

	function renderModule() {
		ensureProjectData();
		const [title, description] = modules[activeModule] || modules.construction;
		document.getElementById('view-title').textContent = title;
		modulePanel.innerHTML = `<h2>${title.replace(' · 3D MODEL', '')}</h2><p>${description}</p>${
			activeModule === 'soil' ? renderSoil()
				: activeModule === 'materials' ? renderMaterials()
					: activeModule === 'objects' ? renderObjects()
						: renderConstruction()
		}${projectEditable ? '' : '<p class="notice">Create or open a project to edit and save project data.</p>'}`;
		document.querySelectorAll('.module-nav [data-module]').forEach(button => {
			if (button.dataset.module === activeModule) {
				button.setAttribute('aria-current', 'page');
			} else {
				button.removeAttribute('aria-current');
			}
		});
	}

	function nextId(items) {
		return items.reduce((maximum, item) => Math.max(maximum, Number(item.id) || 0), 0) + 1;
	}

	function saveProject() {
		if (!projectEditable) {
			document.getElementById('save-status').textContent = 'Create or open a project before saving.';
			return;
		}
		document.getElementById('save-status').textContent = 'Saving project…';
		vscode.postMessage({ command: 'saveProject', project });
	}

	function applyForm(form) {
		const values = new FormData(form);
		const number = key => {
			const value = Number(values.get(key));
			return Number.isFinite(value) ? value : 0;
		};
		if (form.dataset.form === 'soil') {
			const soil = project.soil_site;
			for (const key of ['site_name', 'location', 'latitude', 'longitude', 'length_m', 'width_m', 'area_m2', 'soil_class', 'allowable_bearing_kpa', 'groundwater_depth_m', 'notes']) {
				soil[key] = ['latitude', 'longitude', 'length_m', 'width_m', 'area_m2', 'allowable_bearing_kpa', 'groundwater_depth_m'].includes(key)
					? (values.get(key) === '' ? null : number(key))
					: String(values.get(key) || '');
			}
		} else if (form.dataset.form === 'materials') {
			const model = project.frame_model;
			const material = model.materials.find(item => item.id === selectedMaterialId);
			if (material) {
				material.name = String(values.get('material_name') || '');
				material.material_type = String(values.get('material_type') || 'Other');
				material.design_code = String(values.get('design_code') || '');
				for (const key of ['elastic_modulus', 'shear_modulus', 'density', 'yield_strength']) {
					material[key] = number(key);
					material.properties_enabled ||= {};
					material.properties_enabled[key] = values.has(`enabled_${key}`);
				}
			}
			const section = model.sections.find(item => item.id === selectedSectionId);
			if (section) {
				section.name = String(values.get('section_name') || '');
				section.section_type = String(values.get('section_type') || 'Custom');
				for (const key of ['area', 'torsion_constant', 'moment_of_inertia_y', 'moment_of_inertia_z']) {
					section[key] = number(key);
				}
			}
		} else if (form.dataset.form === 'object') {
			const member = project.frame_model.members.find(item => item.id === selectedMemberId);
			if (member) {
				member.material_id = number('material_id');
				member.section_id = number('section_id');
				project.object_properties[member.id] = {
					...project.object_properties[member.id],
					label: String(values.get('member_label') || ''),
					design_length_m: values.get('design_length_m') === '' ? null : number('design_length_m'),
				};
			}
		} else if (form.dataset.form === 'surface') {
			const surface = project.surface_objects.find(item => item.id === selectedSurfaceId);
			if (surface) {
				surface.label = String(values.get('surface_label') || '');
				surface.points = surface.points.map((point, index) =>
					point.map((coordinate, axis) => number(`p${index}_${axis}`)),
				);
				surface.thickness_m = number('thickness_m');
				surface.material_id = values.get('surface_material_id')
					? number('surface_material_id')
					: null;
			}
		} else if (form.dataset.form === 'add-node') {
			const frame = project.frame_model;
			frame.joints.push({
				id: nextId(frame.joints),
				coordinates: [number('x'), number('y'), number('z')],
				restraints: values.has('fixed')
					? [true, true, true, true, true, true]
					: [false, false, false, false, false, false],
			});
			frame.load_cases ||= [];
			if (!frame.load_cases.length) {
				frame.load_cases.push({ id: 1, name: 'Load Case 1', joint_loads: [] });
			}
		} else if (form.dataset.form === 'add-member') {
			const frame = project.frame_model;
			if (!frame.materials.length || !frame.sections.length) {
				document.getElementById('save-status').textContent = 'Add a material and section before connecting FEM nodes.';
				return;
			}
			const start = number('start_joint');
			const end = number('end_joint');
			if (start === end) {
				document.getElementById('save-status').textContent = 'A frame member must connect two different nodes.';
				return;
			}
			frame.members.push({
				id: nextId(frame.members),
				start_joint: start,
				end_joint: end,
				material_id: frame.materials[0].id,
				section_id: frame.sections[0].id,
				local_z_axis: [0, 0, 1],
			});
		} else if (form.dataset.form === 'add-load') {
			const frame = project.frame_model;
			frame.load_cases ||= [];
			if (!frame.load_cases.length) {
				frame.load_cases.push({ id: 1, name: 'Load Case 1', joint_loads: [] });
			}
			const loadCase = frame.load_cases[0];
			loadCase.joint_loads ||= [];
			loadCase.joint_loads.push({
				joint_id: number('joint_id'),
				values: ['fx', 'fy', 'fz', 'mx', 'my', 'mz'].map(number),
			});
		}
		if (form.dataset.form !== 'soil') {
			delete project.analysis_results;
		}
		renderModule();
		scheduleDraw();
		saveProject();
	}

	async function handleAction(action) {
		if (action === 'import-soil') {
			vscode.postMessage({ command: 'importSoil' });
		} else if (action === 'export-soil') {
			vscode.postMessage({ command: 'exportSoil', project });
		} else if (action === 'import-materials') {
			vscode.postMessage({ command: 'importMaterials' });
		} else if (action === 'export-materials') {
			vscode.postMessage({ command: 'exportMaterials', project });
		} else if (action === 'add-material') {
			const id = nextId(project.frame_model.materials);
			project.frame_model.materials.push({
				id, name: `Material ${id}`,
				material_type: 'Concrete', design_code: '', elastic_modulus: 0, shear_modulus: 0,
				density: 0, yield_strength: 0,
				properties_enabled: { elastic_modulus: true, shear_modulus: true, density: false, yield_strength: false },
			});
			selectedMaterialId = id;
			delete project.analysis_results;
			renderModule();
			saveProject();
		} else if (action === 'add-section') {
			const id = nextId(project.frame_model.sections);
			project.frame_model.sections.push({
				id, name: `Section ${id}`, section_type: 'Rectangular',
				area: 0, torsion_constant: 0, moment_of_inertia_y: 0, moment_of_inertia_z: 0,
			});
			selectedSectionId = id;
			delete project.analysis_results;
			renderModule();
			saveProject();
		} else if (action === 'add-slab' || action === 'add-wall') {
			const wall = action === 'add-wall';
			const id = nextId(project.surface_objects);
			const elevation = Number(project.stories.stories[1]?.elevation) || 3;
			project.surface_objects.push({
				id,
				type: wall ? 'wall' : 'slab',
				label: `${wall ? 'Wall' : 'Slab'} ${id}`,
				thickness_m: wall ? 0.2 : 0.15,
				material_id: null,
				points: wall
					? [[0, 0, 0], [1, 0, 0], [1, 0, elevation], [0, 0, elevation]]
					: [[0, 0, elevation], [1, 0, elevation], [1, 1, elevation], [0, 1, elevation]],
			});
			selectedSurfaceId = id;
			renderModule();
			scheduleDraw();
			saveProject();
		} else if (action === 'generate-building') {
			vscode.postMessage({ command: 'generateBuilding', project });
		} else if (action === 'analyze') {
			vscode.postMessage({ command: 'analyzeFrame', project });
		}
	}

	if (modulePanel) {
		modulePanel.addEventListener('submit', event => {
			event.preventDefault();
			if (!projectEditable) {
				document.getElementById('save-status').textContent = 'Create or open a project before editing.';
				return;
			}
			applyForm(event.target);
		});
		modulePanel.addEventListener('click', event => {
			const actionButton = event.target.closest('[data-action]');
			if (actionButton) {
				if (!projectEditable) {
					document.getElementById('save-status').textContent = 'Create or open a project before editing.';
					return;
				}
				void handleAction(actionButton.dataset.action);
				return;
			}
			const memberButton = event.target.closest('[data-member]');
			if (memberButton) {
				selectedMemberId = Number(memberButton.dataset.member);
				renderModule();
			}
			const surfaceButton = event.target.closest('[data-surface]');
			if (surfaceButton) {
				selectedSurfaceId = Number(surfaceButton.dataset.surface);
				renderModule();
			}
		});
		modulePanel.addEventListener('change', event => {
			if (event.target.id === 'construction-mode') {
				if (!projectEditable) {
					renderModule();
					document.getElementById('save-status').textContent = 'Create or open a project before editing.';
					return;
				}
				project.construction_mode = event.target.value;
				renderModule();
				saveProject();
			} else if (event.target.name === 'material_record') {
				selectedMaterialId = Number(event.target.value);
				renderModule();
			} else if (event.target.name === 'section_record') {
				selectedSectionId = Number(event.target.value);
				renderModule();
			}
		});
		document.getElementById('save-project').addEventListener('click', saveProject);
		document.getElementById('create-project')?.addEventListener('click', () =>
			vscode.postMessage({ command: 'createProject' }));
		document.getElementById('open-project')?.addEventListener('click', () =>
			vscode.postMessage({ command: 'openProject' }));
	}
	window.addEventListener('message', event => {
		const message = event.data;
		if (message?.command === 'project') {
			project = message.project;
			projectEditable = Boolean(message.editable);
			ensureProjectData();
			if (modulePanel) {
				renderModule();
			}
			yaw = -.72;
			pitch = .36;
			zoom = 1;
			scheduleDraw();
		} else if (message?.command === 'saved') {
			if (modulePanel) {
				document.getElementById('save-status').textContent = `Saved ${new Date().toLocaleTimeString()}`;
			}
		} else if (message?.command === 'soilImported') {
			project.soil_site.imported_file = message.fileName;
			project.soil_site.imported_text = message.text;
			project.soil_site.imported_truncated = Boolean(message.truncated);
			Object.assign(project.soil_site, message.fields || {});
			if (modulePanel) {
				renderModule();
			}
			saveProject();
		} else if (message?.command === 'materialsImported') {
			project.frame_model.materials = message.materials;
			if (message.sections?.length) {
				project.frame_model.sections = message.sections;
			}
			selectedMaterialId = project.frame_model.materials[0]?.id;
			selectedSectionId = project.frame_model.sections[0]?.id;
			delete project.analysis_results;
			if (modulePanel) {
				renderModule();
			}
			saveProject();
		} else if (message?.command === 'analysisResult') {
			project.analysis_results = message.results;
			if (modulePanel) {
				document.getElementById('save-status').textContent = 'Analysis results received · saving…';
			}
			saveProject();
		} else if (message?.command === 'operationError') {
			if (modulePanel) {
				document.getElementById('save-status').textContent = message.message;
			}
		}
	});

	function draw() {
		animationFrame = undefined;
		if (!canvas || !context) {
			return;
		}
		const bounds = canvas.getBoundingClientRect();
		if (!bounds.width || !bounds.height) {
			return;
		}
		const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
		const width = Math.round(bounds.width * pixelRatio);
		const height = Math.round(bounds.height * pixelRatio);
		if (canvas.width !== width || canvas.height !== height) {
			canvas.width = width;
			canvas.height = height;
		}
		context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
		context.clearRect(0, 0, bounds.width, bounds.height);
		if (!project) {
			return;
		}

		const geometry = buildGeometry(project);
		if (!geometry.nodes.length || (!geometry.members.length && !geometry.surfaces.length)) {
			if (stats) {
				stats.textContent = 'No frame geometry';
			}
			if (modelName) {
				modelName.textContent = project.settings?.project_name || 'SAEngine project';
			}
			drawCompass(bounds);
			return;
		}

		const points = geometry.nodes.map(node => node.position);
		const minimum = [0, 1, 2].map(axis => Math.min(...points.map(point => point[axis])));
		const maximum = [0, 1, 2].map(axis => Math.max(...points.map(point => point[axis])));
		const center = minimum.map((value, axis) => (value + maximum[axis]) / 2);
		const span = minimum.map((value, axis) => Math.max(maximum[axis] - value, 1));
		const rotate = position => {
			const x = (position[0] - center[0]) / span[0];
			const y = (position[1] - center[1]) / span[1];
			const z = (position[2] - center[2]) / span[2];
			const cosine = Math.cos(yaw);
			const sine = Math.sin(yaw);
			const horizontal = x * cosine - y * sine;
			const depth = x * sine + y * cosine;
			return {
				x: horizontal,
				y: z * Math.cos(pitch) - depth * Math.sin(pitch),
				depth: depth * Math.cos(pitch) + z * Math.sin(pitch),
			};
		};
		const corners = [];
		for (const x of [-0.5, 0.5]) {
			for (const y of [-0.5, 0.5]) {
				for (const z of [-0.5, 0.5]) {
					corners.push(rotate([x, y, z]));
				}
			}
		}
		const plotWidth = bounds.width * 0.77;
		const plotHeight = bounds.height * 0.78;
		const scale = Math.min(
			plotWidth / (Math.max(...corners.map(point => point.x)) - Math.min(...corners.map(point => point.x))),
			plotHeight / (Math.max(...corners.map(point => point.y)) - Math.min(...corners.map(point => point.y))),
		) * zoom;
		const screenCenterX = bounds.width * 0.51;
		const screenCenterY = bounds.height * 0.51;
		const projectPoint = position => {
			const point = rotate(position);
			const perspective = 1 / (1 + point.depth * 0.12);
			return {
				x: screenCenterX + point.x * scale * perspective,
				y: screenCenterY - point.y * scale * perspective,
				depth: point.depth,
			};
		};

		function drawCompass(viewBounds) {
			const origin = { x: 45, y: viewBounds.height - 48 };
			const axisLength = 24;
			const cosine = Math.cos(yaw);
			const sine = Math.sin(yaw);
			const directions = [
				{ vector: [1, 0, 0], positive: 'E', negative: 'W', color: '#ef8e89' },
				{ vector: [0, 1, 0], positive: 'N', negative: 'S', color: '#8fd19a' },
				{ vector: [0, 0, 1], positive: 'UP', negative: 'DOWN', color: '#77c9f1' },
			];
			const rotateDirection = ([x, y, z]) => ({
				x: x * cosine - y * sine,
				y: z * Math.cos(pitch) - (x * sine + y * cosine) * Math.sin(pitch),
			});

			context.save();
			context.font = '600 9px "Segoe UI", sans-serif';
			context.textAlign = 'center';
			context.textBaseline = 'middle';
			context.lineWidth = 1.6;
			for (const direction of directions) {
				const end = rotateDirection(direction.vector);
				const first = {
					x: origin.x - end.x * axisLength,
					y: origin.y + end.y * axisLength,
				};
				const second = {
					x: origin.x + end.x * axisLength,
					y: origin.y - end.y * axisLength,
				};
				context.beginPath();
				context.moveTo(first.x, first.y);
				context.lineTo(second.x, second.y);
				context.strokeStyle = direction.color;
				context.globalAlpha = .82;
				context.stroke();
				context.fillStyle = direction.color;
				context.globalAlpha = 1;
				context.fillText(direction.negative, first.x, first.y);
				context.fillText(direction.positive, second.x, second.y);
			}
			context.beginPath();
			context.arc(origin.x, origin.y, 3, 0, Math.PI * 2);
			context.fillStyle = '#edf3f7';
			context.fill();
			context.restore();
		}

		function strokeMember(member, color, alpha, lineWidth) {
			const first = projectPoint(member.start.position);
			const second = projectPoint(member.end.position);
			context.beginPath();
			context.moveTo(first.x, first.y);
			context.lineTo(second.x, second.y);
			context.strokeStyle = color;
			context.globalAlpha = alpha;
			context.lineWidth = lineWidth;
			context.lineCap = 'round';
			context.stroke();
			return (first.depth + second.depth) / 2;
		}

		context.save();
		context.lineWidth = 1;
		{
			const ground = minimum[2];
			const base = [
				[minimum[0], minimum[1], ground],
				[maximum[0], minimum[1], ground],
				[maximum[0], maximum[1], ground],
				[minimum[0], maximum[1], ground],
			].map(projectPoint);
			context.beginPath();
			context.moveTo(base[0].x, base[0].y);
			for (const corner of base.slice(1)) {
				context.lineTo(corner.x, corner.y);
			}
			context.closePath();
			context.fillStyle = '#55cfbe';
			context.globalAlpha = .045;
			context.fill();
			context.strokeStyle = '#55cfbe';
			context.globalAlpha = .24;
			context.stroke();

			const divisions = 6;
			for (let index = 0; index <= divisions; index++) {
				const fraction = index / divisions;
				const x = minimum[0] + fraction * span[0];
				const y = minimum[1] + fraction * span[1];
				for (const axis of [0, 1]) {
					const first = axis === 0
						? [x, minimum[1], ground]
						: [minimum[0], y, ground];
					const second = axis === 0
						? [x, maximum[1], ground]
						: [maximum[0], y, ground];
					const a = projectPoint(first);
					const b = projectPoint(second);
					context.beginPath();
					context.moveTo(a.x, a.y);
					context.lineTo(b.x, b.y);
					context.strokeStyle = '#33424e';
					context.globalAlpha = .16;
					context.stroke();
				}
			}
		}

		const sortedSurfaces = geometry.surfaces.map(surface => ({
			surface,
			depth: surface.points.reduce((total, point) => total + projectPoint(point).depth, 0) / 4,
		})).sort((a, b) => a.depth - b.depth);
		for (const { surface } of sortedSurfaces) {
			const corners = surface.points.map(projectPoint);
			context.beginPath();
			context.moveTo(corners[0].x, corners[0].y);
			for (const corner of corners.slice(1)) {
				context.lineTo(corner.x, corner.y);
			}
			context.closePath();
			context.fillStyle = surface.type === 'wall' ? '#91a1c8' : '#56cbb8';
			context.globalAlpha = .12;
			context.fill();
			context.globalAlpha = .55;
			context.strokeStyle = surface.type === 'wall' ? '#91a1c8' : '#56cbb8';
			context.lineWidth = 1;
			context.stroke();
		}

		const sortedMembers = geometry.members.map(member => {
			const vertical = Math.abs(member.start.position[2] - member.end.position[2])
				> Math.max(span[2] * 0.001, 1e-9);
			return {
				member,
				vertical,
				depth: (projectPoint(member.start.position).depth
					+ projectPoint(member.end.position).depth) / 2,
			};
		}).sort((a, b) => a.depth - b.depth);
		for (const { member, vertical, depth } of sortedMembers) {
			const emphasis = Math.max(.42, Math.min(.9, .69 + depth * .16));
			strokeMember(
				member,
				vertical ? '#66b9b5' : '#54d7c6',
				emphasis,
				vertical ? 2.1 : 1.65,
			);
		}

		context.restore();
		drawCompass(bounds);
		if (stats) {
			stats.textContent = `${project.frame_model?.joints?.length || geometry.nodes.length} joints  ·  ${geometry.members.length} members  ·  ${geometry.surfaces.length} surfaces`;
		}
		if (modelName) {
			modelName.textContent = project.settings?.project_name || 'SAEngine project';
		}
	}

	function scheduleDraw() {
		if (animationFrame === undefined) {
			animationFrame = window.requestAnimationFrame(draw);
		}
	}

	canvas?.addEventListener('pointerdown', event => {
		drag = { x: event.clientX, y: event.clientY };
		canvas.setPointerCapture(event.pointerId);
	});
	canvas?.addEventListener('pointermove', event => {
		if (!drag) {
			return;
		}
		yaw += (event.clientX - drag.x) * .008;
		pitch = Math.max(-.2, Math.min(1.15, pitch + (event.clientY - drag.y) * .006));
		drag = { x: event.clientX, y: event.clientY };
		scheduleDraw();
	});
	canvas?.addEventListener('pointerup', () => { drag = undefined; });
	canvas?.addEventListener('pointercancel', () => { drag = undefined; });
	canvas?.addEventListener('wheel', event => {
		event.preventDefault();
		zoom = Math.max(.5, Math.min(2.5, zoom * Math.exp(-event.deltaY * .001)));
		scheduleDraw();
	}, { passive: false });
	document.getElementById('reset-view')?.addEventListener('click', () => {
		yaw = -.72;
		pitch = .36;
		zoom = 1;
		scheduleDraw();
	});
	if (canvas) {
		new ResizeObserver(scheduleDraw).observe(canvas);
	}
	document.getElementById('show-3d')?.addEventListener('click', () =>
		vscode.postMessage({ command: 'show3DViewer' }));
	document.getElementById('open-module-file')?.addEventListener('click', () =>
		vscode.postMessage({ command: 'openModuleFile', module: activeModule }));
	project = starterProject();
	ensureProjectData();
	if (modulePanel) {
		renderModule();
	}
	scheduleDraw();
	vscode.postMessage({ command: 'ready' });
})();
