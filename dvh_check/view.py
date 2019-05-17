from bokeh.layouts import column, row
from bokeh.models.widgets import Select, Button, DataTable, TableColumn, NumberFormatter, Div, HTMLTemplateFormatter
from bokeh.models import ColumnDataSource, HoverTool, Spacer
from bokeh.plotting import figure
from dicompylercore import dicomparser, dvhcalc
from protocols import Protocols, MAX_DOSE_VOLUME
from utilities import get_plans
from paths import INBOX_DIR
from structure_aliases import StructureAliases
from bokeh.palettes import Colorblind8 as palette
import itertools
import numpy as np


class ScoreCardView:
    def __init__(self):

        # Initialize Data Objects
        self.dvh = None
        self.dvh_counts = []
        self.dvh_counts_for_plot = None
        self.bin_count = 0
        self.bin_counts = None
        self.roi_keys = None
        self.roi_names = None
        self.roi_key_map = None
        self.plans = None
        self.structures = None
        self.protocol_data = None
        self.roi_override = {}
        self.aliases = StructureAliases()
        self.protocols = Protocols()
        self.source_data = ColumnDataSource(data=dict(roi_name=[], roi_template=[], roi_key=[], volume=[], min_dose=[],
                                                      mean_dose=[], max_dose=[], constraint=[], constraint_calc=[],
                                                      pass_fail=[], calc_type=[]))
        self.source_plot = ColumnDataSource(data=dict(x=[], y=[], color=[], roi=[], roi_key=[]))
        self.colors = itertools.cycle(palette)

        self.__define_layout_objects()
        self.__do_bind()
        self.__do_layout()

        self.update_protocol_data()
        self.initialize_source_data()

    def __define_layout_objects(self):
        # Report heading data
        self.select_plan = Select(title='Plan:', width=400)
        self.button_refresh_plans = Button(label='Scan DICOM Inbox', button_type='primary')
        self.select_protocol = Select(title='Protocol:', options=self.protocols.protocol_names, value='TG101', width=150)
        self.select_fx = Select(title='Fractions:', value='3', options=self.fractionation_options, width=60)
        self.button_calculate = Button(label='Calculate Scorecard', button_type='primary')
        self.button_delete_roi = Button(label='Delete Constraint', button_type='warning')
        self.button_calculate_dvhs = Button(label='Calculate DVHs', button_type='primary', width=200)
        self.select_roi_template = Select(title='Template ROI:')
        self.select_roi = Select(title='Plan ROI:')
        self.max_dose_volume = Div(text="<b>Point defined as %scc" % MAX_DOSE_VOLUME)

        self.columns = [TableColumn(field="roi_template", title="Template ROI"),
                        TableColumn(field="roi_name", title="ROI"),
                        TableColumn(field='volume', title='Volume (cc)', formatter=NumberFormatter(format="0.00")),
                        TableColumn(field='min_dose', title='Min Dose (Gy)', formatter=NumberFormatter(format="0.00")),
                        TableColumn(field='mean_dose', title='Mean Dose (Gy)', formatter=NumberFormatter(format="0.00")),
                        TableColumn(field='max_dose', title='Max Dose (Gy)', formatter=NumberFormatter(format="0.00")),
                        TableColumn(field='constraint', title='Constraint'),
                        TableColumn(field='constraint_calc', title='Value', formatter=NumberFormatter(format="0.00")),
                        TableColumn(field='pass_fail', title='Pass/Fail', formatter=self.__pass_fail_formatter)]
        self.data_table = DataTable(source=self.source_data, columns=self.columns, index_position=None,
                                    width=1000, height=300)

        tools = "pan,wheel_zoom,box_zoom,reset,crosshair,save"
        self.plot = figure(plot_width=800, plot_height=475, tools=tools, active_drag="box_zoom")
        # Set x and y axis labels
        self.plot.xaxis.axis_label = "Dose (Gy)"
        self.plot.yaxis.axis_label = "Normalized Volume"
        self.plot.min_border_left = 60
        self.plot.min_border_bottom = 60
        self.plot.add_tools(HoverTool(show_arrow=False, line_policy='next',
                                      tooltips=[('Plan ROI', '@roi'),
                                                ('Dose', '$x'),
                                                ('Volume', '$y')]))
        self.plot.xaxis.axis_label_text_font_size = "12pt"
        self.plot.yaxis.axis_label_text_font_size = "12pt"
        self.plot.xaxis.major_label_text_font_size = "10pt"
        self.plot.yaxis.major_label_text_font_size = "10pt"
        self.plot.yaxis.axis_label_text_baseline = "bottom"
        self.plot.lod_factor = 100  # level of detail during interactive plot events

        self.plot.multi_line('x', 'y', source=self.source_plot,
                             selection_color='color', line_width=3, alpha=0,
                             line_dash='solid', nonselection_alpha=0, selection_alpha=1)

        columns = [TableColumn(field="roi", title="Select Structures to Plot")]
        self.plot_rois = DataTable(source=self.source_plot, columns=columns, index_position=None,
                                   width=200, height=350)

    def __do_bind(self):
        self.button_calculate.on_click(self.initialize_source_data)
        self.button_delete_roi.on_click(self.delete_selected_rows)
        self.select_protocol.on_change('value', self.protocol_listener)
        self.select_fx.on_change('value', self.fx_listener)
        self.button_refresh_plans.on_click(self.update_plan_options)
        self.select_plan.on_change('value', self.plan_listener)
        self.select_roi_template.on_change('value', self.template_roi_listener)
        self.select_roi.on_change('value', self.roi_listener)
        self.source_data.selected.on_change('indices', self.source_select)
        self.button_calculate_dvhs.on_click(self.update_dvh_plot)

    def __do_layout(self):

        self.layout = column(self.button_refresh_plans,
                             row(self.select_plan, self.select_protocol, self.select_fx),
                             row(self.button_calculate, self.button_delete_roi),
                             row(self.select_roi_template, self.select_roi),
                             self.max_dose_volume,
                             self.data_table,
                             row(self.plot, Spacer(width=10), column(self.button_calculate_dvhs,
                                                                     self.plot_rois)))

    @property
    def __pass_fail_formatter(self):
        # Data tables
        # custom js to highlight mismatches in red with white text
        template = """
                           <div style="background:<%= 
                               (function colorfrommismatch(){
                                   if(pass_fail != "" ){
                                       if(pass_fail == "Fail"){
                                          return('HIGHLIGHT_COLOR_FAIL')
                                       }
                                       if(pass_fail == "Pass"){
                                          return('HIGHLIGHT_COLOR_PASS')
                                       }
                                   }
                                   }()) %>; 
                               color: <%= 
                                    (function colorfrommismatch(){
                                        if(pass_fail == "Fail"){return('TEXT_COLOR_FAIL')}
                                        }()) %>;"> 
                           <%= value %>
                           </div>
                           """
        template = template.replace('HIGHLIGHT_COLOR_FAIL', 'red')
        template = template.replace('TEXT_COLOR_FAIL', 'white')
        template = template.replace('HIGHLIGHT_COLOR_PASS', 'lightgreen')
        template = template.replace('TEXT_COLOR_PASS', 'black')
        return HTMLTemplateFormatter(template=template)

    # Properties -------------------------------------------------------------------
    @property
    def fractionation(self):
        return "%sFx" % self.select_fx.value

    @property
    def fractionation_options(self):
        return self.protocols.get_fractionations(self.protocol)

    @property
    def protocol(self):
        return self.select_protocol.value

    @property
    def current_struct_file(self):
        return self.plans[self.select_plan.value]['rtstruct']

    # Listeners -------------------------------------------------------------------
    def protocol_listener(self, attr, old, new):
        self.select_fx.options = self.fractionation_options
        if self.select_fx.value not in self.select_fx.options:
            self.select_fx.value = self.select_fx.options[0]
        else:  # Changing select_fx.value will prompt the following two lines
            self.update_protocol_data()
            self.initialize_source_data()

    def fx_listener(self, attr, old, new):
        self.update_protocol_data()
        self.initialize_source_data()

    def plan_listener(self, attr, old, new):
        self.roi_override = {}
        if new in list(self.plans):
            self.initialize_source_data()

    def template_roi_listener(self, attr, old, new):
        self.update_roi_select()

    def roi_listener(self, attr, old, new):
        template_rois = self.source_data.data['roi_template']
        indices = [i for i, roi in enumerate(template_rois) if roi == self.select_roi_template.value]
        if indices:
            patches = {'roi_name': [(i, new) for i in indices]}
            self.source_data.patch(patches)
        if new:
            self.roi_override[self.select_roi_template.value] = new
            self.button_calculate.button_type = 'success'
            total = len(indices)
            for i in indices:
                self.button_calculate.label = 'Calculating ScoreCard %s of %s' % (i+1, total)
                key = self.roi_key_map[new]
                self.calculate_dvh(key)
                self.update_table_row(i, key)
                self.source_data.patch({'roi_key': [(i, key)]})
                self.update_constraint(i)
            self.button_calculate.label = 'Calculate Scorecard'
            self.button_calculate.button_type = 'primary'
        else:
            if self.button_calculate.button_type == 'primary' and self.select_roi_template.value in self.roi_override:
                self.roi_override.pop(self.select_roi_template.value)
            patches = {'volume': [(i, 0.) for i in indices],
                       'min_dose': [(i, 0.) for i in indices],
                       'mean_dose': [(i, 0.) for i in indices],
                       'max_dose': [(i, 0.) for i in indices],
                       'constraint_calc': [(i, 0.) for i in indices],
                       'pass_fail': [(i, '') for i in indices],
                       'roi_key': [(i, '') for i in indices]}
            self.source_data.patch(patches)

    def source_select(self, attr, old, new):
        if new:
            self.select_roi_template.value = self.source_data.data['roi_template'][new[0]]

    # Methods -------------------------------------------------------------------
    def update_protocol_data(self):
        self.protocol_data = self.protocols.get_column_data(self.protocol, self.fractionation)

    def initialize_source_data(self):
        data = self.protocol_data
        self.bin_counts = None
        self.bin_count = None
        self.dvh = {}
        self.dvh_counts_for_plot = []
        self.dvh_counts = []
        row_count = len(data['roi_template'])
        new_data = {'roi_template': data['roi_template'],
                    'roi_key': [''] * row_count,
                    'roi_name': [''] * row_count,
                    'volume': [''] * row_count,
                    'min_dose': [''] * row_count,
                    'mean_dose': [''] * row_count,
                    'max_dose': [''] * row_count,
                    'constraint': data['string_rep'],
                    'constraint_calc': [''] * row_count,
                    'pass_fail': [''] * row_count,
                    'calc_type': data['calc_type']}

        self.source_plot.data = {'x': [], 'y': [], 'color': [], 'roi': [], 'roi_key': []}

        self.source_data.data = new_data
        self.update_roi_template_select()
        if self.select_plan.value:
            self.button_calculate.label = 'Calculating Scorecard...'
            self.button_calculate.button_type = 'success'
            self.update_plan_structures()

    def delete_selected_rows(self):
        selected_indices = self.source_data.selected.indices
        selected_indices.sort(reverse=True)
        if not selected_indices:
            selected_indices = [0]
        data = self.source_data.data
        for index in selected_indices:
            for key in list(data):
                data[key].pop(index)

        self.source_data.data = data
        self.source_data.selected.indices = []

    def update_roi_template_select(self):
        options = list(set(self.source_data.data['roi_template']))
        options.sort()
        self.select_roi_template.options = options
        if self.select_roi_template.value not in options:
            self.select_roi_template.value = options[0]

    def update_plan_options(self):
        self.button_refresh_plans.button_type = 'success'
        self.button_refresh_plans.label = 'Updating...'
        self.plans = get_plans(INBOX_DIR)
        self.select_plan.options = list(self.plans)
        self.button_refresh_plans.button_type = 'primary'
        self.button_refresh_plans.label = 'Scan DICOM Inbox'
        if self.select_plan.value not in list(self.plans):
            self.select_plan.value = list(self.plans)[0]

    def update_plan_structures(self):
        self.structures = dicomparser.DicomParser(self.current_struct_file).GetStructures()
        self.roi_keys = [key for key in self.structures if self.structures[key]['type'].upper() != 'MARKER']
        self.roi_names = [str(self.structures[key]['name']) for key in self.roi_keys]
        self.roi_key_map = {name: self.roi_keys[i] for i, name in enumerate(self.roi_names)}
        self.select_roi.options = [''] + self.roi_names
        self.update_roi_select()
        self.match_rois()

    def update_roi_select(self):
        index = self.source_data.data['roi_template'].index(self.select_roi_template.value)
        self.select_roi.value = self.source_data.data['roi_name'][index]

    def match_rois(self):
        matches = self.aliases.match_protocol_rois(self.source_data.data['roi_template'], self.roi_names)
        patches = {'roi_name': [], 'roi_key': []}
        for i, protocol_roi in enumerate(self.source_data.data['roi_template']):
            if protocol_roi in list(matches):
                match = matches[protocol_roi]
            else:
                match = ''
            if protocol_roi in list(self.roi_override):
                match = self.roi_override[protocol_roi]
            if match:
                key = self.roi_key_map[match]
            else:
                key = ''
            patches['roi_name'].append((i, match))
            patches['roi_key'].append((i, key))
        self.source_data.patch(patches)
        self.update_roi_select()
        self.calculate_protocol_dvhs()

    def update_table_row(self, index, key):
        patch = {'volume': [(index, self.dvh[key].volume)],
                 'min_dose': [(index, self.dvh[key].min)],
                 'mean_dose': [(index, self.dvh[key].mean)],
                 'max_dose': [(index, self.dvh[key].max)]}
        self.source_data.patch(patch)

    def calculate_dvh(self, key):
        if key not in list(self.dvh):
            files = self.plans[self.select_plan.value]
            self.dvh[key] = dvhcalc.get_dvh(files['rtstruct'], files['rtdose'], key)

    def calculate_dvhs(self):
        current_button_type = self.button_calculate.button_type
        current_button_label = self.button_calculate.label
        self.button_calculate_dvhs.button_type = 'success'

        files = self.plans[self.select_plan.value]
        total = len(self.roi_keys)
        for i, key in enumerate(list(self.roi_keys)):
            self.button_calculate_dvhs.label = 'Calculating DVH: %s of %s' % (i+1, total)
            if key not in list(self.dvh):
                self.dvh[key] = dvhcalc.get_dvh(files['rtstruct'], files['rtdose'], key)
        self.dvh_counts = [self.dvh[key].counts for key in self.roi_keys]
        self.button_calculate.button_type = current_button_type
        self.button_calculate.label = current_button_label

    def calculate_protocol_dvhs(self):
        self.dvh = {}
        total = len([key for key in self.source_data.data['roi_key'] if key != ''])
        counter = 1
        for i, key in enumerate(self.source_data.data['roi_key']):
            if key:
                self.button_calculate.label = 'Calculating Scorecard %s of %s' % (counter, total)
                self.calculate_dvh(key)
                self.update_table_row(i, key)
                self.update_constraint(i)
                counter += 1

        self.button_calculate.label = 'Calculate Scorecard'
        self.button_calculate.button_type = 'primary'

    def update_constraint(self, index):

        if self.source_data.data['roi_name'][index]:
            constraint = self.calculate_constraint(index)

            operator = self.protocol_data['operator'][index]
            threshold = self.protocol_data['threshold_value'][index]

            if constraint is not None:
                if operator == '<':
                    status = constraint < threshold
                else:
                    status = constraint > threshold
                status = ['Fail', 'Pass'][status]
            else:
                status = ''

            self.source_data.patch({'constraint_calc': [(index, constraint)],
                                    'pass_fail': [(index, status)]})

    def calculate_constraint(self, index):
        dvh = self.dvh[self.source_data.data['roi_key'][index]]
        calc_type = self.source_data.data['calc_type'][index]
        input_value = self.protocol_data['input_value'][index]
        if calc_type == 'Volume':
            ans = dvh.dose_constraint(input_value, volume_units='cm3')
            return float(str(ans).split(' ')[0])
        if calc_type == 'Dose':
            ans = dvh.volume_constraint(input_value, dose_units='Gy')
            return float(str(ans).split(' ')[0])
        if calc_type == 'Mean':
            return self.source_data.data['mean_dose'][index]
        if calc_type == 'MVS':
            ans = dvh.volume_constraint(input_value, dose_units='Gy')
            ans = float(str(ans).split(' ')[0])
            return self.source_data.data['volume'][index] - ans

        return None

    @property
    def volumes(self):
        return np.array([self.dvh[key].volume for key in self.roi_keys])

    def pad_dvh_counts(self):
        self.bin_count = max([len(dvh) for dvh in self.dvh_counts])
        self.dvh_counts_for_plot = []
        self.bin_counts = []
        for dvh in self.dvh_counts:
            if dvh[0]:
                self.dvh_counts_for_plot.append(np.divide(dvh, dvh[0]))
            else:
                self.dvh_counts_for_plot.append(np.array([0] * self.bin_count))
            np.append(self.dvh_counts_for_plot[-1], [0])  # ensure last value is 0
            x_axis = np.divide(np.array(list(range(len(self.dvh_counts_for_plot[-1])))), 100.)
            self.bin_counts.append(x_axis)

    def update_dvh_plot(self):
        self.calculate_dvhs()
        self.pad_dvh_counts()
        colors = [color for j, color in zip(range(len(self.dvh_counts_for_plot)), self.colors)]
        self.source_plot.data = {'x': self.bin_counts,
                                 'y': self.dvh_counts_for_plot,
                                 'color': colors,
                                 'roi': self.roi_names,
                                 'roi_key': self.roi_keys}
        self.button_calculate_dvhs.label = 'Calculate DVHs'
        self.button_calculate_dvhs.button_type = 'primary'
