"""The Soil Report buttons the soil feature modules register: id, title and help per tab."""

FEATURES = {
    "soil": [
        {
            "title": "Borehole Log Editor",
            "id": "soil.boreholeLogEditor",
            "help": "Edits the graphical borehole log with strata, samples and water strikes.",
        },
        {
            "title": "Depth Ruler",
            "id": "soil.depthRuler",
            "help": "Shows a scaled depth ruler beside the log strip.",
        },
        {
            "title": "Graphic Log Style",
            "id": "soil.graphicLogStyle",
            "help": "Sets hatching, colours and symbols for each soil type.",
        },
        {
            "title": "Groundwater Strike",
            "id": "soil.groundwaterStrike",
            "help": "Records perched and standing water levels per borehole.",
        },
        {
            "title": "SPT Hammer Type",
            "id": "soil.sptHammerType",
            "help": "Sets hammer energy ratio and rod corrections for SPT.",
        },
        {
            "title": "Field Density Test",
            "id": "soil.fieldDensityTest",
            "help": "Enters sand replacement and core cutter density results.",
        },
        {
            "title": "Falling Head Test",
            "id": "soil.fallingHeadTest",
            "help": "Adds variable and falling head permeability readings.",
        },
        {
            "title": "Borehole Plan",
            "id": "soil.boreholePlan",
            "help": "Plots all boreholes on the site plan with labels.",
        },
        {
            "title": "Coordinate System",
            "id": "soil.coordinateSystem",
            "help": "Sets the coordinate reference system for all locations.",
        },
        {
            "title": "Google Earth KML",
            "id": "soil.googleEarthKml",
            "help": "Exports borehole positions as a KML overlay.",
        },
        {
            "title": "Vane Shear Test",
            "id": "soil.vaneShearTest",
            "help": "Derive undrained shear strength from field vane readings with correction "
            "factors.",
        },
        {
            "title": "Pressuremeter Test",
            "id": "soil.pressuremeterTest",
            "help": "Reduce pressuremeter curves into modulus and limit pressure profiles.",
        },
        {
            "title": "Lugeon Test",
            "id": "soil.lugeonTest",
            "help": "Interpret packer water tests to report rock mass permeability in Lugeon "
            "units.",
        },
        {
            "title": "Undisturbed Sample",
            "id": "soil.undisturbedSample",
            "help": "Register tube samples with depth, recovery and specimen quality class.",
        },
        {
            "title": "Split Spoon Sample",
            "id": "soil.splitSpoonSample",
            "help": "Record split spoon recovery and align it with blow count intervals.",
        },
        {
            "title": "Sample Preservation",
            "id": "soil.samplePreservation",
            "help": "Track sealing, waxing and storage conditions for each retained sample.",
        },
        {
            "title": "Hole Deviation Check",
            "id": "soil.holeDeviationCheck",
            "help": "Compare surveyed borehole inclination against the planned vertical alignment.",
        },
        {
            "title": "Missing Interval Scan",
            "id": "soil.missingIntervalScan",
            "help": "Flag depth ranges in a log that have no description or test result.",
        },
    ],
    "soilTests": [
        {
            "title": "Sample Register",
            "id": "soilTests.sampleRegister",
            "help": "Lists disturbed, undisturbed and core samples with depths.",
        },
        {
            "title": "Core Photos",
            "id": "soilTests.corePhotos",
            "help": "Attaches core box photographs to borehole records.",
        },
        {
            "title": "Chain of Custody",
            "id": "soilTests.chainOfCustody",
            "help": "Tracks sample transport and storage history.",
        },
        {
            "title": "Schedule Tests",
            "id": "soilTests.scheduleTests",
            "help": "Builds the laboratory testing programme per borehole.",
        },
        {
            "title": "Atterberg Limits",
            "id": "soilTests.atterbergLimits",
            "help": "Enters liquid and plastic limit test results.",
        },
        {
            "title": "Direct Shear",
            "id": "soilTests.directShear",
            "help": "Reduces direct shear tests to cohesion and friction angle.",
        },
        {
            "title": "Triaxial Suite",
            "id": "soilTests.triaxialSuite",
            "help": "Processes UU, CU and CD triaxial test series.",
        },
        {
            "title": "Consolidation Test",
            "id": "soilTests.consolidationTest",
            "help": "Fits consolidation curves and compression indices.",
        },
        {
            "title": "SPT Correlations",
            "id": "soilTests.sptCorrelations",
            "help": "Derives strength and stiffness from corrected SPT values.",
        },
        {
            "title": "Phi From SPT",
            "id": "soilTests.phiFromSpt",
            "help": "Correlates friction angle with corrected blow counts.",
        },
        {
            "title": "Cu From SPT",
            "id": "soilTests.cuFromSpt",
            "help": "Estimates undrained shear strength for cohesive soils.",
        },
        {
            "title": "Moisture Content",
            "id": "soilTests.moistureContent",
            "help": "Record oven dry moisture contents and summarise them by stratum.",
        },
        {
            "title": "Specific Gravity",
            "id": "soilTests.specificGravity",
            "help": "Enter particle specific gravity results used in void ratio calculations.",
        },
        {
            "title": "Particle Size Analysis",
            "id": "soilTests.particleSizeAnalysis",
            "help": "Combine sieve and hydrometer data into a single grading curve.",
        },
        {
            "title": "UCS Test",
            "id": "soilTests.ucsTest",
            "help": "Reduce uniaxial compression tests into intact rock strength values.",
        },
        {
            "title": "Point Load Index",
            "id": "soilTests.pointLoadIndex",
            "help": "Convert point load readings to an equivalent strength index for "
            "classification.",
        },
        {
            "title": "Brazilian Tensile",
            "id": "soilTests.brazilianTensile",
            "help": "Compute indirect tensile strength from disc splitting test measurements.",
        },
        {
            "title": "Outlier Flag",
            "id": "soilTests.outlierFlag",
            "help": "Flag test results that deviate unusually from results on the same stratum.",
        },
        {
            "title": "Repeat Test Advice",
            "id": "soilTests.repeatTestAdvice",
            "help": "Recommend which samples should be retested before values are adopted.",
        },
    ],
    "soilProfile": [
        {
            "title": "Build Ground Model",
            "id": "soilProfile.buildGroundModel",
            "help": "Builds a 3D ground model from correlated borehole layers.",
        },
        {
            "title": "Fence Diagram",
            "id": "soilProfile.fenceDiagram",
            "help": "Draws a fence diagram through selected borehole alignments.",
        },
        {
            "title": "Cross Sections",
            "id": "soilProfile.crossSections",
            "help": "Cuts geological cross sections along any alignment.",
        },
        {
            "title": "Slice View",
            "id": "soilProfile.sliceView",
            "help": "Slices the ground model at a chosen elevation.",
        },
        {
            "title": "Correlate Layers",
            "id": "soilProfile.correlateLayers",
            "help": "Links equivalent strata across boreholes interactively.",
        },
        {
            "title": "Lens Detection",
            "id": "soilProfile.lensDetection",
            "help": "Flags lenticular pockets that break simple layer correlation.",
        },
        {
            "title": "Pinch-Out Cleanup",
            "id": "soilProfile.pinchOutCleanup",
            "help": "Repairs layers that thin out between boreholes.",
        },
        {
            "title": "Interpolate Surface",
            "id": "soilProfile.interpolateSurface",
            "help": "Interpolates stratum surfaces from borehole elevations.",
        },
        {
            "title": "Contour Map",
            "id": "soilProfile.contourMap",
            "help": "Generates contour maps for any stratum surface.",
        },
        {
            "title": "Surface Volume",
            "id": "soilProfile.surfaceVolume",
            "help": "Computes layer volumes between two stratum surfaces.",
        },
        {"title": "CPT Import", "id": "soilProfile.cptImport", "help": "CPT Import."},
        {
            "title": "Robertson Soil Class",
            "id": "soilProfile.robertsonSoilClass",
            "help": "Robertson Soil Class.",
        },
        {
            "title": "Cone Resistance Qc",
            "id": "soilProfile.coneResistanceQc",
            "help": "Cone Resistance Qc.",
        },
        {
            "title": "Sleeve Friction Fs",
            "id": "soilProfile.sleeveFrictionFs",
            "help": "Sleeve Friction Fs.",
        },
        {
            "title": "Dissipation Test",
            "id": "soilProfile.dissipationTest",
            "help": "Fit pore pressure decay curves to estimate horizontal consolidation "
            "coefficient.",
        },
        {
            "title": "Pore Pressure Profile",
            "id": "soilProfile.porePressureProfile",
            "help": "Plot measured pore pressures against depth with hydrostatic reference lines.",
        },
        {
            "title": "Hydrostatic Correction",
            "id": "soilProfile.hydrostaticCorrection",
            "help": "Remove hydrostatic head so excess pore pressures can be compared across "
            "holes.",
        },
        {
            "title": "Excess Pore Pressure",
            "id": "soilProfile.excessPorePressure",
            "help": "Compute pore pressure ratio from CPT penetration to screen for liquefaction.",
        },
        {
            "title": "Equilibrium Pore Pressure",
            "id": "soilProfile.equilibriumPorePressure",
            "help": "Estimate stabilised groundwater pressure from multiple readings in one hole.",
        },
        {
            "title": "Model Validation",
            "id": "soilProfile.modelValidation",
            "help": "Check the built ground model against logged layer boundaries and flag "
            "conflicts.",
        },
        {
            "title": "Layer Thickness Map",
            "id": "soilProfile.layerThicknessMap",
            "help": "Generate plan contours of individual layer thickness across the site.",
        },
        {
            "title": "Depth Datum Shift",
            "id": "soilProfile.depthDatumShift",
            "help": "Move the entire model to a new elevation datum while preserving "
            "relative depths.",
        },
        {
            "title": "Zone Assignment",
            "id": "soilProfile.zoneAssignment",
            "help": "Group correlated layers into geotechnical zones used by design calculations.",
        },
        {
            "title": "Section Regeneration",
            "id": "soilProfile.sectionRegeneration",
            "help": "Rebuild all fence and cross sections after the ground model changes.",
        },
    ],
    "soilSeismic": [
        {
            "title": "Site Class Map",
            "id": "soilSeismic.siteClassMap",
            "help": "Maps site classes across the plot from all boreholes.",
        },
        {
            "title": "Vs30 Profile",
            "id": "soilSeismic.vs30Profile",
            "help": "Plots shear wave velocity against depth for each borehole.",
        },
        {
            "title": "Site Period",
            "id": "soilSeismic.sitePeriod",
            "help": "Estimates the fundamental site period from the velocity profile.",
        },
        {
            "title": "Liquefaction Map",
            "id": "soilSeismic.liquefactionMap",
            "help": "Maps liquefaction potential across the site area.",
        },
        {
            "title": "CSR & CRR",
            "id": "soilSeismic.csrCrr",
            "help": "Computes cyclic stress and resistance ratios per layer.",
        },
        {
            "title": "Post-Liquefaction Settlement",
            "id": "soilSeismic.postLiquefactionSettlement",
            "help": "Estimates settlement after liquefaction triggering.",
        },
        {
            "title": "Lateral Spread",
            "id": "soilSeismic.lateralSpread",
            "help": "Screens for lateral spreading near slopes and water.",
        },
        {
            "title": "Design Spectrum",
            "id": "soilSeismic.designSpectrum",
            "help": "Builds the site-specific design response spectrum.",
        },
        {
            "title": "Site Amplification",
            "id": "soilSeismic.siteAmplification",
            "help": "Applies site amplification factors to bedrock motion.",
        },
        {
            "title": "Soil Profile Type",
            "id": "soilSeismic.soilProfileType",
            "help": "Assigns the code soil profile type per borehole.",
        },
        {
            "title": "PGA Contours",
            "id": "soilSeismic.pgaContours",
            "help": "Map peak ground acceleration values across the site from the selected "
            "hazard source.",
        },
        {
            "title": "Arias Intensity",
            "id": "soilSeismic.ariasIntensity",
            "help": "Compute energy based intensity from accelerograms to judge shaking severity.",
        },
        {
            "title": "Record Duration",
            "id": "soilSeismic.recordDuration",
            "help": "Report significant duration of selected ground motion records for time "
            "history work.",
        },
        {
            "title": "Time History Pick",
            "id": "soilSeismic.timeHistoryPick",
            "help": "Select and scale accelerograms for the site response analysis.",
        },
        {
            "title": "Transfer Function",
            "id": "soilSeismic.transferFunction",
            "help": "Compute the soil column transfer function between bedrock and surface motion.",
        },
        {
            "title": "Amplification Factor",
            "id": "soilSeismic.amplificationFactor",
            "help": "Derive period dependent amplification factors for the analysed soil profile.",
        },
        {
            "title": "Shear Wave Profile",
            "id": "soilSeismic.shearWaveProfile",
            "help": "Build a shear wave velocity profile from downhole and MASW measurements.",
        },
        {
            "title": "Hysteretic Damping",
            "id": "soilSeismic.hystereticDamping",
            "help": "Assign strain dependent damping curves to each modelled soil layer.",
        },
        {
            "title": "Seismic Earth Pressure",
            "id": "soilSeismic.seismicEarthPressure",
            "help": "Add dynamic earth pressure increments to static wall pressures during "
            "shaking.",
        },
        {
            "title": "Slope Displacement",
            "id": "soilSeismic.slopeDisplacement",
            "help": "Estimate permanent slope movement from seismic loading on the critical "
            "surface.",
        },
        {
            "title": "Retaining Displacement",
            "id": "soilSeismic.retainingDisplacement",
            "help": "Check allowable movement of retaining walls under seismic earth pressures.",
        },
    ],
    "soilBearing": [
        {
            "title": "Plate Load Test",
            "id": "soilBearing.plateLoadTest",
            "help": "Interprets plate load tests into modulus and bearing values.",
        },
        {
            "title": "Presumptive Values",
            "id": "soilBearing.presumptiveValues",
            "help": "Applies presumptive bearing values from the selected code.",
        },
        {
            "title": "Bearing Contours",
            "id": "soilBearing.bearingContours",
            "help": "Maps allowable bearing pressure across the site.",
        },
        {
            "title": "Immediate Settlement",
            "id": "soilBearing.immediateSettlement",
            "help": "Estimates elastic settlement from footing pressure and modulus.",
        },
        {
            "title": "Consolidation Settlement",
            "id": "soilBearing.consolidationSettlement",
            "help": "Computes primary consolidation settlement from lab data.",
        },
        {
            "title": "Differential Settlement",
            "id": "soilBearing.differentialSettlement",
            "help": "Checks angular distortion between adjacent footings.",
        },
        {
            "title": "Settlement Contours",
            "id": "soilBearing.settlementContours",
            "help": "Draws settlement contours for the whole site.",
        },
        {
            "title": "Soil Springs",
            "id": "soilBearing.soilSprings",
            "help": "Derives vertical and horizontal spring stiffness for supports.",
        },
        {
            "title": "Subgrade Modulus",
            "id": "soilBearing.subgradeModulus",
            "help": "Calculates modulus of subgrade reaction for rafts and slabs.",
        },
        {
            "title": "Spring Stiffness Table",
            "id": "soilBearing.springStiffnessTable",
            "help": "Lists spring values per footing and per soil layer.",
        },
        {
            "title": "Limit Equilibrium LEM",
            "id": "soilBearing.limitEquilibriumLem",
            "help": "Limit Equilibrium LEM.",
        },
        {
            "title": "Strength Reduction FEM",
            "id": "soilBearing.strengthReductionFem",
            "help": "Strength Reduction FEM.",
        },
        {
            "title": "Critical Slip Surface",
            "id": "soilBearing.criticalSlipSurface",
            "help": "Critical Slip Surface.",
        },
        {
            "title": "Factor of Safety Map",
            "id": "soilBearing.factorOfSafetyMap",
            "help": "Factor of Safety Map.",
        },
        {
            "title": "Stone Column Design",
            "id": "soilBearing.stoneColumnDesign",
            "help": "Size granular columns to reach a target composite bearing capacity.",
        },
        {
            "title": "Dynamic Compaction",
            "id": "soilBearing.dynamicCompaction",
            "help": "Estimate improvement depth and settlement reduction from compaction energy.",
        },
        {
            "title": "Raft Pressure Check",
            "id": "soilBearing.raftPressureCheck",
            "help": "Evaluate contact pressure distribution beneath a raft for the governing "
            "load case.",
        },
        {
            "title": "Buoyancy Check",
            "id": "soilBearing.buoyancyCheck",
            "help": "Compare uplift from groundwater against the submerged weight of the raft.",
        },
    ],
    "soilReport": [
        {
            "title": "Compile Soil Report",
            "id": "soilReport.compileSoilReport",
            "help": "Assembles the geotechnical report from all investigation data.",
        },
        {
            "title": "Executive Summary",
            "id": "soilReport.executiveSummary",
            "help": "Drafts a summary of ground conditions and recommendations.",
        },
        {
            "title": "Recommendations",
            "id": "soilReport.recommendations",
            "help": "Generates foundation recommendations per structure.",
        },
        {
            "title": "Design Values Table",
            "id": "soilReport.designValuesTable",
            "help": "Publishes adopted geotechnical design values per layer.",
        },
        {
            "title": "Borehole Sheets",
            "id": "soilReport.boreholeSheets",
            "help": "Produces one drawing sheet per borehole log.",
        },
        {
            "title": "Test Certificates",
            "id": "soilReport.testCertificates",
            "help": "Attaches laboratory certificates to the report set.",
        },
        {
            "title": "Section Sheets",
            "id": "soilReport.sectionSheets",
            "help": "Places geological sections onto report sheets.",
        },
        {
            "title": "Export Soil PDF",
            "id": "soilReport.exportSoilPdf",
            "help": "Exports the complete soil report as a PDF file.",
        },
        {
            "title": "Export Soil Word",
            "id": "soilReport.exportSoilWord",
            "help": "Exports the editable soil report to Word format.",
        },
        {
            "title": "Report Templates",
            "id": "soilReport.reportTemplates",
            "help": "Chooses the report template and chapter structure.",
        },
        {
            "title": "Consistency Check",
            "id": "soilReport.consistencyCheck",
            "help": "Flags contradictory bearing, water and classification data.",
        },
        {
            "title": "Review Sign-Off",
            "id": "soilReport.reviewSignOff",
            "help": "Records reviewer approval and locks the report revision.",
        },
        {
            "title": "Location Plan Figure",
            "id": "soilReport.locationPlanFigure",
            "help": "Compose a scaled site location plan with boreholes and coordinates.",
        },
        {
            "title": "Profile Figure Set",
            "id": "soilReport.profileFigureSet",
            "help": "Generate the full set of geological profile figures for the report.",
        },
        {
            "title": "Contour Figure",
            "id": "soilReport.contourFigure",
            "help": "Insert ground surface and rock head contour maps into the report.",
        },
        {
            "title": "Chart Inserts",
            "id": "soilReport.chartInserts",
            "help": "Place test result charts at report anchors so numbering stays automatic.",
        },
        {
            "title": "Figure Numbering",
            "id": "soilReport.figureNumbering",
            "help": "Renumber all report figures in order of appearance with linked captions.",
        },
        {
            "title": "Caption Styles",
            "id": "soilReport.captionStyles",
            "help": "Apply consistent caption formatting to figures, tables and charts.",
        },
        {
            "title": "Drawing Register",
            "id": "soilReport.drawingRegister",
            "help": "List every issued drawing with revision, date and approval status.",
        },
        {
            "title": "Report Appendices",
            "id": "soilReport.reportAppendices",
            "help": "Assemble appendices for logs, test sheets and calculation records.",
        },
        {
            "title": "Data Pack Export",
            "id": "soilReport.dataPackExport",
            "help": "Bundle raw and interpreted data into a structured delivery folder.",
        },
        {
            "title": "Revision Compare",
            "id": "soilReport.revisionCompare",
            "help": "Highlight text and figure changes between two report revisions.",
        },
        {
            "title": "Issue Transmittal",
            "id": "soilReport.issueTransmittal",
            "help": "Generate a transmittal sheet recording recipients and issued documents.",
        },
        {
            "title": "Archive Snapshot",
            "id": "soilReport.archiveSnapshot",
            "help": "Freeze the current report set into an immutable archive package.",
        },
    ],
    "soilDesign": [
        {
            "title": "Design Parameter Sets",
            "id": "soilDesign.designParameterSets",
            "help": "Groups adopted geotechnical parameters for each analysis.",
        },
        {
            "title": "Parameter Table",
            "id": "soilDesign.parameterTable",
            "help": "Edits strength, stiffness and permeability values per layer.",
        },
        {
            "title": "Adopt Parameters",
            "id": "soilDesign.adoptParameters",
            "help": "Marks a parameter set as the design basis for foundations.",
        },
        {
            "title": "Characteristic Values",
            "id": "soilDesign.characteristicValues",
            "help": "Derives characteristic values with statistical reduction.",
        },
        {
            "title": "Effective Stress",
            "id": "soilDesign.effectiveStress",
            "help": "Computes effective stress profiles with depth.",
        },
        {
            "title": "Shear Modulus",
            "id": "soilDesign.shearModulus",
            "help": "Derives small-strain and operational shear modulus.",
        },
        {
            "title": "Earth Pressure Coefficients",
            "id": "soilDesign.earthPressureCoefficients",
            "help": "Reports K0, Ka and Kp for each design layer.",
        },
        {
            "title": "Allowable Pressure",
            "id": "soilDesign.allowablePressure",
            "help": "Derive allowable bearing pressure from strength and settlement criteria.",
        },
        {
            "title": "Footing Size Advice",
            "id": "soilDesign.footingSizeAdvice",
            "help": "Suggest preliminary footing sizes for the reported column loads.",
        },
        {
            "title": "Settlement Estimate",
            "id": "soilDesign.settlementEstimate",
            "help": "Estimate immediate and consolidation settlement for the proposed footing.",
        },
        {
            "title": "Sliding Resistance",
            "id": "soilDesign.slidingResistance",
            "help": "Check resistance against sliding from base friction and passive pressure.",
        },
        {
            "title": "Uplift Resistance",
            "id": "soilDesign.upliftResistance",
            "help": "Evaluate uplift resistance from overburden and structural dead weight.",
        },
        {
            "title": "Pile Capacity Advice",
            "id": "soilDesign.pileCapacityAdvice",
            "help": "Recommend pile working capacity from the interpreted ground profile.",
        },
        {
            "title": "Negative Friction",
            "id": "soilDesign.negativeFriction",
            "help": "Quantify downdrag on piles where fill or soft soil settles around the shaft.",
        },
        {
            "title": "Pile Group Settlement",
            "id": "soilDesign.pileGroupSettlement",
            "help": "Estimate group settlement using interaction factors between adjacent piles.",
        },
        {
            "title": "Driven Resistance",
            "id": "soilDesign.drivenResistance",
            "help": "Assess driveability and set refusal criteria for the chosen hammer.",
        },
        {
            "title": "Wall Friction Angle",
            "id": "soilDesign.wallFrictionAngle",
            "help": "Recommend interface friction angles for the selected wall material and "
            "backfill.",
        },
        {
            "title": "Base Friction",
            "id": "soilDesign.baseFriction",
            "help": "Provide base friction coefficients for sliding checks on retaining walls.",
        },
        {
            "title": "Overturning Advice",
            "id": "soilDesign.overturningAdvice",
            "help": "Report the governing overturning condition and suggested base width.",
        },
        {
            "title": "Eccentricity Advice",
            "id": "soilDesign.eccentricityAdvice",
            "help": "Limit resultant eccentricity and report the required bearing pressure "
            "adjustment.",
        },
        {
            "title": "Parameter Traceability",
            "id": "soilDesign.parameterTraceability",
            "help": "Link every adopted design value back to its source test and interpretation.",
        },
        {
            "title": "Design Note Export",
            "id": "soilDesign.designNoteExport",
            "help": "Produce a geotechnical design note summarising assumptions and values.",
        },
        {
            "title": "Uncertainty Summary",
            "id": "soilDesign.uncertaintySummary",
            "help": "Summarise parameter variability and its effect on the governing design value.",
        },
        {
            "title": "Sensitivity Study",
            "id": "soilDesign.sensitivityStudy",
            "help": "Vary key parameters to show how the design result responds to uncertainty.",
        },
    ],
    "soilEarth": [
        {
            "title": "Wall Friction",
            "id": "soilEarth.wallFriction",
            "help": "Sets interface friction between soil and wall material.",
        },
        {
            "title": "Backfill Properties",
            "id": "soilEarth.backfillProperties",
            "help": "Defines compacted backfill strength and density.",
        },
        {
            "title": "Compaction Loads",
            "id": "soilEarth.compactionLoads",
            "help": "Applies construction compaction-induced lateral loads.",
        },
        {
            "title": "Sulfate Attack",
            "id": "soilEarth.sulfateAttack",
            "help": "Classifies sulfate exposure and required cement type.",
        },
        {
            "title": "Chloride Content",
            "id": "soilEarth.chlorideContent",
            "help": "Reports chloride ion content against durability limits.",
        },
        {
            "title": "pH & Resistivity",
            "id": "soilEarth.phResistivity",
            "help": "Records pH and resistivity for corrosion assessment.",
        },
        {
            "title": "Durability Class",
            "id": "soilEarth.durabilityClass",
            "help": "Assigns exposure and durability classes to foundations.",
        },
        {
            "title": "Basement Wall Pressure",
            "id": "soilEarth.basementWallPressure",
            "help": "Build pressure envelopes for basement walls with restrained top conditions.",
        },
        {
            "title": "Anchored Wall Pressure",
            "id": "soilEarth.anchoredWallPressure",
            "help": "Distribute earth pressure across anchored wall levels for each "
            "construction stage.",
        },
        {
            "title": "Braced Excavation Pressure",
            "id": "soilEarth.bracedExcavationPressure",
            "help": "Apply apparent pressure diagrams to braced excavation support design.",
        },
        {
            "title": "Silo Pressure",
            "id": "soilEarth.siloPressure",
            "help": "Compute lateral pressures in silos and bunkers from stored material "
            "properties.",
        },
        {
            "title": "Slope Surcharge",
            "id": "soilEarth.slopeSurcharge",
            "help": "Convert slope geometry into an equivalent surcharge on the retaining wall.",
        },
        {
            "title": "Railway Surcharge",
            "id": "soilEarth.railwaySurcharge",
            "help": "Apply railway loading strips behind walls using standard axle arrangements.",
        },
        {
            "title": "Traffic Surcharge",
            "id": "soilEarth.trafficSurcharge",
            "help": "Add highway traffic loading as a surcharge behind retaining structures.",
        },
        {
            "title": "Compaction Induced Pressure",
            "id": "soilEarth.compactionInducedPressure",
            "help": "Account for extra lateral pressure caused by compaction plant near the wall.",
        },
        {
            "title": "Total Sulphate",
            "id": "soilEarth.totalSulphate",
            "help": "Classify sulphate exposure from soil and groundwater test results.",
        },
        {
            "title": "Organic Content",
            "id": "soilEarth.organicContent",
            "help": "Record organic content values that affect compressibility and aggressivity.",
        },
        {
            "title": "Aggressivity Index",
            "id": "soilEarth.aggressivityIndex",
            "help": "Combine chemical results into an overall aggressivity rating for buried "
            "concrete.",
        },
        {
            "title": "Cement Type Advice",
            "id": "soilEarth.cementTypeAdvice",
            "help": "Recommend suitable cement and binder combinations for the measured exposure.",
        },
    ],
    "soilSite": [
        {
            "title": "Import DEM",
            "id": "soilSite.importDem",
            "help": "Imports a digital elevation model for the site surface.",
        },
        {
            "title": "Contours From DEM",
            "id": "soilSite.contoursFromDem",
            "help": "Generates site contours directly from the imported terrain.",
        },
        {
            "title": "Slope Map",
            "id": "soilSite.slopeMap",
            "help": "Colours the site by slope steepness for planning.",
        },
        {
            "title": "Set CRS",
            "id": "soilSite.setCrs",
            "help": "Assigns a coordinate reference system to the site model.",
        },
        {
            "title": "Export KMZ",
            "id": "soilSite.exportKmz",
            "help": "Exports the georeferenced site model as a KMZ file.",
        },
        {
            "title": "Basemap",
            "id": "soilSite.basemap",
            "help": "Loads aerial or street basemaps behind the site plan.",
        },
        {
            "title": "Flood Zone",
            "id": "soilSite.floodZone",
            "help": "Overlays flood hazard zones on the site boundary.",
        },
        {
            "title": "Easements",
            "id": "soilSite.easements",
            "help": "Marks easements and rights of way that constrain foundations.",
        },
        {
            "title": "Setbacks",
            "id": "soilSite.setbacks",
            "help": "Checks building setbacks against the plot boundary.",
        },
        {
            "title": "Catchment Delineation",
            "id": "soilSite.catchmentDelineation",
            "help": "Delineate the site catchment boundary from the loaded terrain surface.",
        },
        {
            "title": "Flow Accumulation",
            "id": "soilSite.flowAccumulation",
            "help": "Trace concentrated runoff paths to place drainage and attenuation measures.",
        },
        {
            "title": "Flood Depth Map",
            "id": "soilSite.floodDepthMap",
            "help": "Estimate flood water depth across the site for the chosen return period.",
        },
        {
            "title": "Point Cloud Import",
            "id": "soilSite.pointCloudImport",
            "help": "Load survey point clouds and convert them into a triangulated ground surface.",
        },
        {
            "title": "Coordinate Transform",
            "id": "soilSite.coordinateTransform",
            "help": "Reproject imported survey data between coordinate reference systems.",
        },
        {
            "title": "Elevation Check",
            "id": "soilSite.elevationCheck",
            "help": "Compare survey spot levels with the terrain model and list large residuals.",
        },
        {
            "title": "Plot Boundaries",
            "id": "soilSite.plotBoundaries",
            "help": "Import cadastral plot boundaries and clip them to the project site area.",
        },
        {
            "title": "Right Of Way",
            "id": "soilSite.rightOfWay",
            "help": "Mark rights of way and utility corridors that constrain site development.",
        },
        {
            "title": "Land Use Map",
            "id": "soilSite.landUseMap",
            "help": "Capture surrounding land uses to support noise, dust and access assessments.",
        },
    ],
}
