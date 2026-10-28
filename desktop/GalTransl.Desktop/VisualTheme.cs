using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Media;

namespace GalTransl.Desktop;

// Three base colours; hierarchy comes from alpha, spacing and thin highlights.
public static class VisualTheme {
    public static readonly Color Base=Color.FromRgb(32,34,38),Surface=Color.FromRgb(73,77,84),Ink=Color.FromRgb(238,239,241);
    public static SolidColorBrush Brush(Color color,double alpha=1)=>new(Color.FromArgb((byte)Math.Round(255*Math.Clamp(alpha,0,1)),color.R,color.G,color.B));
    public static void Apply(Window window){
        window.Background=Brush(Base);window.Foreground=Brush(Ink);window.FontFamily=new FontFamily("Microsoft YaHei UI");
        window.Resources[SystemColors.HighlightBrushKey]=Brush(Surface);window.Resources[SystemColors.HighlightTextBrushKey]=Brush(Ink);
        window.Resources[SystemColors.WindowBrushKey]=Brush(Base);window.Resources[SystemColors.WindowTextBrushKey]=Brush(Ink);
        window.Resources[SystemColors.ControlBrushKey]=Brush(Surface);window.Resources[SystemColors.ControlTextBrushKey]=Brush(Ink);
        var input=new Style(typeof(TextBox));input.Setters.Add(new Setter(Control.BackgroundProperty,Brush(Surface,.35)));
        input.Setters.Add(new Setter(Control.ForegroundProperty,Brush(Ink)));input.Setters.Add(new Setter(Control.BorderBrushProperty,Brush(Surface)));
        input.Setters.Add(new Setter(Control.BorderThicknessProperty,new Thickness(1)));input.Setters.Add(new Setter(TextBoxBase.CaretBrushProperty,Brush(Ink)));
        var inputBorder=new FrameworkElementFactory(typeof(Border));inputBorder.SetValue(Border.CornerRadiusProperty,new CornerRadius(8));
        inputBorder.SetValue(Border.BackgroundProperty,new TemplateBindingExtension(Control.BackgroundProperty));inputBorder.SetValue(Border.BorderBrushProperty,new TemplateBindingExtension(Control.BorderBrushProperty));
        inputBorder.SetValue(Border.BorderThicknessProperty,new TemplateBindingExtension(Control.BorderThicknessProperty));inputBorder.SetValue(Border.PaddingProperty,new TemplateBindingExtension(Control.PaddingProperty));
        inputBorder.AppendChild(new FrameworkElementFactory(typeof(ScrollViewer),"PART_ContentHost"));
        input.Setters.Add(new Setter(Control.TemplateProperty,new ControlTemplate(typeof(TextBox)){VisualTree=inputBorder}));
        window.Resources[typeof(TextBox)]=input;
        var list=new Style(typeof(ListBox));list.Setters.Add(new Setter(Control.BackgroundProperty,Brush(Base)));
        list.Setters.Add(new Setter(Control.ForegroundProperty,Brush(Ink)));list.Setters.Add(new Setter(Control.BorderBrushProperty,Brush(Surface)));
        window.Resources[typeof(ListBox)]=list;
        var combo=new Style(typeof(ComboBox));combo.Setters.Add(new Setter(Control.BackgroundProperty,Brush(Surface,.4)));
        combo.Setters.Add(new Setter(Control.ForegroundProperty,Brush(Ink)));combo.Setters.Add(new Setter(Control.BorderBrushProperty,Brush(Surface)));
        combo.Setters.Add(new Setter(Control.TemplateProperty,ComboTemplate()));window.Resources[typeof(ComboBox)]=combo;
        var item=new Style(typeof(ComboBoxItem));item.Setters.Add(new Setter(Control.ForegroundProperty,Brush(Ink)));
        item.Setters.Add(new Setter(Control.PaddingProperty,new Thickness(10,6,10,6)));
        item.Setters.Add(new Setter(Control.TemplateProperty,ItemTemplate(typeof(ComboBoxItem))));
        foreach(var property in new[]{ComboBoxItem.IsHighlightedProperty,ComboBoxItem.IsSelectedProperty}){
            var trigger=new Trigger{Property=property,Value=true};trigger.Setters.Add(new Setter(Control.BackgroundProperty,Brush(Surface)));item.Triggers.Add(trigger);
        }
        window.Resources[typeof(ComboBoxItem)]=item;
        var listItem=new Style(typeof(ListBoxItem));listItem.Setters.Add(new Setter(Control.ForegroundProperty,Brush(Ink)));
        listItem.Setters.Add(new Setter(Control.PaddingProperty,new Thickness(10,6,10,6)));listItem.Setters.Add(new Setter(Control.TemplateProperty,ItemTemplate(typeof(ListBoxItem))));
        var selectedItem=new Trigger{Property=ListBoxItem.IsSelectedProperty,Value=true};selectedItem.Setters.Add(new Setter(Control.BackgroundProperty,Brush(Surface)));listItem.Triggers.Add(selectedItem);window.Resources[typeof(ListBoxItem)]=listItem;
        var checkbox=new Style(typeof(CheckBox));var row=new FrameworkElementFactory(typeof(DockPanel));
        var tickBox=new FrameworkElementFactory(typeof(Border));tickBox.SetValue(FrameworkElement.WidthProperty,18.0);tickBox.SetValue(FrameworkElement.HeightProperty,18.0);tickBox.SetValue(FrameworkElement.MarginProperty,new Thickness(0,0,8,0));
        tickBox.SetValue(Border.CornerRadiusProperty,new CornerRadius(4));tickBox.SetValue(Border.BackgroundProperty,Brush(Surface,.5));tickBox.SetValue(Border.BorderBrushProperty,Brush(Surface));tickBox.SetValue(Border.BorderThicknessProperty,new Thickness(1));
        var mark=new FrameworkElementFactory(typeof(TextBlock),"Mark");mark.SetValue(TextBlock.TextProperty,"✓");mark.SetValue(TextBlock.ForegroundProperty,Brush(Ink));mark.SetValue(FrameworkElement.HorizontalAlignmentProperty,HorizontalAlignment.Center);mark.SetValue(FrameworkElement.VerticalAlignmentProperty,VerticalAlignment.Center);mark.SetValue(UIElement.VisibilityProperty,Visibility.Collapsed);tickBox.AppendChild(mark);row.AppendChild(tickBox);
        var label=new FrameworkElementFactory(typeof(ContentPresenter));label.SetValue(FrameworkElement.VerticalAlignmentProperty,VerticalAlignment.Center);row.AppendChild(label);
        var checkTemplate=new ControlTemplate(typeof(CheckBox)){VisualTree=row};var checkedTrigger=new Trigger{Property=ToggleButton.IsCheckedProperty,Value=true};checkedTrigger.Setters.Add(new Setter(UIElement.VisibilityProperty,Visibility.Visible,"Mark"));checkTemplate.Triggers.Add(checkedTrigger);
        checkbox.Setters.Add(new Setter(Control.TemplateProperty,checkTemplate));window.Resources[typeof(CheckBox)]=checkbox;
    }
    static ControlTemplate ItemTemplate(Type type){
        var border=new FrameworkElementFactory(typeof(Border));border.SetValue(Border.CornerRadiusProperty,new CornerRadius(6));
        border.SetValue(Border.BackgroundProperty,new TemplateBindingExtension(Control.BackgroundProperty));border.SetValue(Border.PaddingProperty,new TemplateBindingExtension(Control.PaddingProperty));
        border.AppendChild(new FrameworkElementFactory(typeof(ContentPresenter)));return new ControlTemplate(type){VisualTree=border};
    }
    static ControlTemplate ComboTemplate(){
        var grid=new FrameworkElementFactory(typeof(Grid));
        var toggle=new FrameworkElementFactory(typeof(ToggleButton));toggle.SetValue(UIElement.FocusableProperty,false);
        toggle.SetBinding(ToggleButton.IsCheckedProperty,new Binding("IsDropDownOpen"){RelativeSource=new(RelativeSourceMode.TemplatedParent),Mode=BindingMode.TwoWay});
        toggle.SetValue(Control.BackgroundProperty,new TemplateBindingExtension(Control.BackgroundProperty));
        toggle.SetValue(Control.BorderBrushProperty,new TemplateBindingExtension(Control.BorderBrushProperty));toggle.SetValue(Control.BorderThicknessProperty,new Thickness(1));
        var chrome=new FrameworkElementFactory(typeof(Border));chrome.SetValue(Border.CornerRadiusProperty,new CornerRadius(8));
        chrome.SetValue(Border.BackgroundProperty,new TemplateBindingExtension(Control.BackgroundProperty));chrome.SetValue(Border.BorderBrushProperty,new TemplateBindingExtension(Control.BorderBrushProperty));chrome.SetValue(Border.BorderThicknessProperty,new Thickness(1));
        toggle.SetValue(Control.TemplateProperty,new ControlTemplate(typeof(ToggleButton)){VisualTree=chrome});grid.AppendChild(toggle);
        var selected=new FrameworkElementFactory(typeof(ContentPresenter));selected.SetValue(UIElement.IsHitTestVisibleProperty,false);selected.SetValue(FrameworkElement.MarginProperty,new Thickness(12,9,30,9));
        selected.SetValue(ContentPresenter.ContentProperty,new TemplateBindingExtension(ComboBox.SelectionBoxItemProperty));selected.SetValue(ContentPresenter.ContentTemplateProperty,new TemplateBindingExtension(ComboBox.SelectionBoxItemTemplateProperty));
        selected.SetValue(ContentPresenter.ContentTemplateSelectorProperty,new TemplateBindingExtension(ItemsControl.ItemTemplateSelectorProperty));
        selected.SetValue(ContentPresenter.ContentStringFormatProperty,new TemplateBindingExtension(ComboBox.SelectionBoxItemStringFormatProperty));grid.AppendChild(selected);
        var arrow=new FrameworkElementFactory(typeof(TextBlock));arrow.SetValue(TextBlock.TextProperty,"⌄");arrow.SetValue(TextBlock.ForegroundProperty,Brush(Ink,.75));arrow.SetValue(UIElement.IsHitTestVisibleProperty,false);
        arrow.SetValue(FrameworkElement.HorizontalAlignmentProperty,HorizontalAlignment.Right);arrow.SetValue(FrameworkElement.VerticalAlignmentProperty,VerticalAlignment.Center);arrow.SetValue(FrameworkElement.MarginProperty,new Thickness(0,0,12,0));grid.AppendChild(arrow);
        var popup=new FrameworkElementFactory(typeof(Popup),"PART_Popup");popup.SetValue(Popup.PlacementProperty,PlacementMode.Bottom);popup.SetValue(Popup.AllowsTransparencyProperty,true);popup.SetValue(Popup.StaysOpenProperty,false);
        popup.SetBinding(Popup.IsOpenProperty,new Binding("IsDropDownOpen"){RelativeSource=new(RelativeSourceMode.TemplatedParent),Mode=BindingMode.TwoWay});
        var menu=new FrameworkElementFactory(typeof(Border));menu.SetValue(Border.BackgroundProperty,Brush(Base));menu.SetValue(Border.BorderBrushProperty,Brush(Surface));menu.SetValue(Border.BorderThicknessProperty,new Thickness(1));menu.SetValue(Border.CornerRadiusProperty,new CornerRadius(8));menu.SetValue(Border.PaddingProperty,new Thickness(4));
        menu.SetBinding(FrameworkElement.MinWidthProperty,new Binding("ActualWidth"){RelativeSource=new(RelativeSourceMode.TemplatedParent)});
        var scroll=new FrameworkElementFactory(typeof(ScrollViewer));scroll.SetValue(FrameworkElement.MaxHeightProperty,280.0);scroll.SetValue(ScrollViewer.VerticalScrollBarVisibilityProperty,ScrollBarVisibility.Auto);
        scroll.AppendChild(new FrameworkElementFactory(typeof(ItemsPresenter)));menu.AppendChild(scroll);popup.AppendChild(menu);grid.AppendChild(popup);
        return new ControlTemplate(typeof(ComboBox)){VisualTree=grid};
    }
}
